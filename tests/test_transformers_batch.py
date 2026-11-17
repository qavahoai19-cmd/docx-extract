from contextlib import nullcontext
import io
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

Image = pytest.importorskip("PIL.Image")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "colab_ocr_server"))
from transformers_batch import batched_vision, decode_outputs, infer_batch


class Tokenizer:
    eos_token_id = 1

    def decode(self, tokens):
        return " ".join(map(str, tokens))


def test_batch_decode_stops_at_each_rows_eos_and_rejects_truncation():
    results = decode_outputs([[10, 1, 1, 1], [20, 21, 1, 1], [30, 31]], Tokenizer())
    assert [row["latex"] for row in results] == ["10", "20 21", ""]
    assert results[2]["error"] == "token limit reached"


def test_batch_generation_preserves_image_order_prompt_masks_and_completeness(monkeypatch):
    class Tensor:
        def __init__(self, data):
            self.data = data

        def to(self, **kwargs):
            assert kwargs == {"device": "cuda:0", "dtype": "fp16"}
            return self

        def __getitem__(self, index):
            if isinstance(index, tuple):
                rows, columns = index
                return Tensor([row[columns] for row in self.data[rows]])
            return Tensor(self.data[index])

        def detach(self):
            return self

        def cpu(self):
            return self

        def tolist(self):
            return self.data

    fake_torch = SimpleNamespace(
        long="long", bool="bool", tensor=lambda data, **_: Tensor(data),
        stack=lambda tensors: Tensor([tensor.data for tensor in tensors]),
        zeros=lambda shape, **_: Tensor({"shape": shape}),
        ones=lambda shape, **_: Tensor([[1] * shape[1] for _ in range(shape[0])]),
        ones_like=lambda tensor: Tensor([[1] * len(row) for row in tensor.data]),
        inference_mode=nullcontext, autocast=lambda *args, **kwargs: nullcontext(),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    def transform(**kwargs):
        assert kwargs == {"mean": (0.5, 0.5, 0.5), "std": (0.5, 0.5, 0.5), "normalize": True}
        return lambda image: Tensor(image.getpixel((512, 512)))

    helpers = {"format_messages": lambda **_: "left<image>right",
               "text_encode": lambda tokenizer, text, **_: [2] if text == "left" else [3],
               "BasicImageTransform": transform}

    class Model:
        infer = SimpleNamespace(__func__=SimpleNamespace(__globals__=helpers))

        def parameters(self):
            yield SimpleNamespace(device="cuda:0")

        def generate(self, inputs, **kwargs):
            assert len(inputs.data) == 2 and inputs.data[0] == inputs.data[1]
            assert inputs.data[0].count(128815) == 257
            assert [sum(mask) for mask in kwargs["images_seq_mask"].data] == [257, 257]
            assert [entry[1].data[0] for entry in kwargs["images"]] == [(255, 0, 0), (0, 0, 255)]
            assert kwargs["images_spatial_crop"].data == [[1, 1], [1, 1]]
            assert kwargs["use_cache"] and not kwargs["do_sample"]
            assert kwargs["max_new_tokens"] == 8192
            return Tensor([inputs.data[0] + [10, 1, 1], inputs.data[1] + [20, 21, 1]])

    images = []
    for color in ("red", "blue"):
        buffer = io.BytesIO()
        Image.new("RGB", (20, 10), color).save(buffer, "PNG")
        images.append(buffer.getvalue())
    results = infer_batch(Model(), Tokenizer(), images, prompt="<image>\nOCR this formula to LaTeX.",
                          image_size=1024, dtype="fp16")
    assert [row["latex"] for row in results] == ["10", "20 21"]


@pytest.mark.parametrize("invalid_mask", [False, True])
def test_vision_batch_keeps_each_images_features_and_restores_forward(monkeypatch, invalid_mask):
    np = pytest.importorskip("numpy")

    class Tensor:
        def __init__(self, data):
            self.data = np.asarray(data)
            self.shape, self.dtype, self.device = self.data.shape, self.data.dtype, "test"

        def reshape(self, *shape): return Tensor(self.data.reshape(*shape))
        def expand(self, *shape): return Tensor(np.broadcast_to(self.data, tuple(old if new == -1 else new for old, new in zip(self.shape, shape))))
        def sum(self, dim): return Tensor(self.data.sum(axis=dim))
        def tolist(self): return self.data.tolist()
        def unsqueeze(self, dim): return Tensor(np.expand_dims(self.data, dim))
        def to(self, **kwargs): return self

        def masked_scatter_(self, mask, values):
            self.data[np.broadcast_to(mask.data, self.shape)] = values.data.flatten()

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        cat=lambda tensors, dim: Tensor(np.concatenate([tensor.data for tensor in tensors], axis=dim))))

    class Base:
        def forward(self, **kwargs):
            assert kwargs["input_ids"] is None and "images" not in kwargs
            return kwargs["inputs_embeds"]

    class DeepseekOCR2Model(Base):
        view_seperator = Tensor([99])

        def forward(self, **kwargs): return "original"
        def get_input_embeddings(self): return lambda ids: Tensor(np.zeros((*ids.shape, 1), dtype=int))
        def sam_model(self, originals): return originals
        def qwen2_model(self, features): return features
        def projector(self, features): return features

    vision = DeepseekOCR2Model()
    model = SimpleNamespace(model=vision)
    inputs = {"input_ids": Tensor([[0, 1, 2, 3, 4]] * 2),
              "images": [(None, Tensor([[[10], [11]]])), (None, Tensor([[[20], [21]]]))],
              "images_seq_mask": Tensor([[False, True, True, True, False],
                                          [False, True, True, not invalid_mask, False]])}
    if invalid_mask:
        with pytest.raises(ValueError, match="token positions"), batched_vision(model):
            vision.forward(**inputs)
    else:
        with batched_vision(model):
            result = vision.forward(**inputs)
            assert result.data[:, :, 0].tolist() == [[0, 10, 11, 99, 0], [0, 20, 21, 99, 0]]
            assert vision.forward(input_ids=Tensor([[5], [6]]), images=inputs["images"]) == "original"
    assert "forward" not in vision.__dict__ and vision.forward() == "original"
