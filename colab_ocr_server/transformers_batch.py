"""Optional fixed-resolution batches for the pinned DeepSeek-OCR-2 model.

Preserves the official non-crop prompt, transform and greedy decoding.
The fixed-resolution vision pass and decoding are batched. GPU throughput and
output parity must be measured before enabling this mode.
"""

import io
from contextlib import contextmanager
from types import MethodType
from PIL import Image, ImageOps


@contextmanager
def batched_vision(model):
    """Adapt this instance for one no-crop generate call, restoring it always."""
    import torch

    vision = getattr(model, "model", None)
    if vision is None or type(vision).__name__ != "DeepseekOCR2Model":
        yield
        return
    original = vision.forward
    marker = object()
    saved = vision.__dict__.get("forward", marker)
    base_forward = super(type(vision), vision).forward

    def forward(this, *args, **kwargs):
        ids, images = kwargs.get("input_ids"), kwargs.get("images")
        if args or ids is None or ids.shape[1] == 1 or not images or len(images) == 1:
            return original(*args, **kwargs)
        embeds = this.get_input_embeddings()(ids)
        originals = torch.cat([image[1] for image in images], dim=0)
        features = this.projector(this.qwen2_model(this.sam_model(originals)))
        separator = this.view_seperator.reshape(1, 1, -1).expand(features.shape[0], 1, -1)
        features = torch.cat([features, separator], dim=1)
        mask = kwargs["images_seq_mask"]
        if (features.shape[0] != embeds.shape[0] or features.shape[-1] != embeds.shape[-1]
                or any(count != features.shape[1] for count in mask.sum(dim=1).tolist())):
            raise ValueError("Vision features do not match each image's token positions")
        embeds.masked_scatter_(mask.unsqueeze(-1).to(device=embeds.device), features.to(dtype=embeds.dtype))
        base_kwargs = {key: value for key, value in kwargs.items()
                       if key not in {"images", "images_seq_mask", "images_spatial_crop"}}
        base_kwargs.update(input_ids=None, inputs_embeds=embeds)
        return base_forward(**base_kwargs)

    vision.forward = MethodType(forward, vision)
    try:
        yield
    finally:
        if saved is marker:
            del vision.forward
        else:
            vision.forward = saved


def decode_outputs(rows, tokenizer):
    eos = tokenizer.eos_token_id
    if eos is None:
        raise ValueError("Tokenizer must define EOS for complete-output checks")
    eos_ids = {eos} if isinstance(eos, int) else set(eos)
    results = []
    for tokens in rows:
        end = next((index for index, token in enumerate(tokens) if token in eos_ids), None)
        if end is None:
            results.append({"latex": "", "error": "token limit reached"})
        else:
            latex = tokenizer.decode(tokens[:end]).strip()
            results.append({"latex": latex, "error": "" if latex else "empty OCR result"})
    return results


def infer_batch(model, tokenizer, pngs, *, prompt, image_size, dtype, max_new_tokens=8192):
    import torch

    if not pngs:
        return []
    if image_size not in {768, 1024} or prompt.count("<image>") != 1:
        raise ValueError("Batch requires one image and a supported fixed resolution")
    helpers = model.infer.__func__.__globals__
    conversation = [{"role": "<|User|>", "content": prompt},
                    {"role": "<|Assistant|>", "content": ""}]
    formatted = helpers["format_messages"](conversations=conversation, sft_format="plain", system_prompt="")
    left, right = formatted.split("<image>")
    encode = helpers["text_encode"]
    prefix = encode(tokenizer, left, bos=False, eos=False)
    suffix = encode(tokenizer, right, bos=False, eos=False)
    image_tokens = [128815] * ((image_size // 64) ** 2 + 1)
    ids = [0] + prefix + image_tokens + suffix
    mask = [False] * (1 + len(prefix)) + [True] * len(image_tokens) + [False] * len(suffix)
    transform = helpers["BasicImageTransform"](mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5), normalize=True)
    tensors = []
    for png in pngs:
        with Image.open(io.BytesIO(png)) as source:
            image = source.convert("RGB")
            if image_size <= 768:
                image = image.resize((image_size, image_size))
            image = ImageOps.pad(image, (image_size, image_size), color=(127, 127, 127))
            tensors.append(transform(image))
    device = next(model.parameters()).device
    images = torch.stack(tensors).to(device=device, dtype=dtype)
    patches = torch.zeros((1, 3, image_size, image_size), device=device, dtype=dtype)
    input_ids = torch.tensor([ids] * len(pngs), dtype=torch.long, device=device)
    with torch.inference_mode(), torch.autocast("cuda", dtype=dtype), batched_vision(model):
        generated = model.generate(
            input_ids, attention_mask=torch.ones_like(input_ids),
            images=[(patches, images[index:index + 1]) for index in range(len(pngs))],
            images_seq_mask=torch.tensor([mask] * len(pngs), dtype=torch.bool, device=device),
            images_spatial_crop=torch.ones((len(pngs), 2), dtype=torch.long),
            do_sample=False, temperature=0.0, eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.eos_token_id, max_new_tokens=max_new_tokens,
            no_repeat_ngram_size=35, use_cache=True,
        )
    rows = generated[:, len(ids):].detach().cpu().tolist()
    if len(rows) != len(pngs):
        raise ValueError("Model returned a different batch length")
    return decode_outputs(rows, tokenizer)
