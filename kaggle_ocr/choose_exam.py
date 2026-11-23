"""Copy toàn bộ vào một cell mới: chọn DOCX thật, rồi bấm Đọc đề đã chọn.

Chỉ là bộ chọn file cho pipeline đã có, không thay model/cấu hình OCR.
Không tự chọn đề Toán. Không khởi chạy OCR khi chỉ mở giao diện.
"""
import base64
import builtins
import hashlib
import html
import importlib.util
from pathlib import Path
import subprocess
import sys
import time
import traceback

try:
    import ipywidgets as widgets
except ModuleNotFoundError:
    subprocess.run([sys.executable, "-m", "pip", "install", "ipywidgets>=8,<9"], check=True)
    import ipywidgets as widgets
from IPython.display import HTML, FileLink, IFrame, display


def load_existing_pipeline(namespace):
    module = namespace.get("pipeline")
    if callable(getattr(module, "run", None)):
        return module
    root = Path(namespace.get("RUN_ROOT", "/kaggle/working/hybrid_original_fixed"))
    path = root / "hybrid_ocr_original_fixed.py"
    if not path.is_file():
        raise RuntimeError("Chưa tìm thấy pipeline đã nạp. Cần cell OCR chính đã được thiết lập trong cùng phiên.")
    source = path.read_text(encoding="utf-8")
    if "def run_worker(" not in source or "def self_script_path(" not in source:
        raise RuntimeError("File pipeline không đúng bản Pandoc + DeepSeek-OCR đang dùng.")
    spec = importlib.util.spec_from_file_location("existing_exam_pipeline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    namespace["pipeline"] = module
    return module


class ExamPicker:
    def __init__(self, namespace, runner=None, search_root="/kaggle/input"):
        self.namespace = namespace
        self.runner = runner if runner is not None else load_existing_pipeline(namespace)
        self.search_root = Path(search_root)
        self.busy = self.refreshing = False
        self.choice = widgets.Dropdown(description="Chọn DOCX:", options=[("— Chọn đề muốn đọc —", "")],
                                       layout=widgets.Layout(width="98%"))
        self.refresh_button = widgets.Button(description="Làm mới danh sách", icon="refresh")
        self.run_button = widgets.Button(description="Đọc đề đã chọn", icon="play", button_style="success", disabled=True,
                                         layout=widgets.Layout(width="240px"))
        self.status = widgets.HTML("Chọn đúng tên file ở trên, sau đó bấm Đọc đề đã chọn.")
        self.logs = widgets.Output(layout=widgets.Layout(max_height="350px", overflow="auto"))
        self.preview = widgets.Output()
        self.choice.observe(self.on_choose, names="value")
        self.refresh_button.on_click(self.refresh)
        self.run_button.on_click(self.on_run)
        self.view = widgets.VBox([widgets.HTML("<h3>Đọc một đề khác</h3><p>Chọn file cụ thể bên dưới. Không tự lấy đề Toán hay kết quả cũ.</p>"),
                                  self.choice, widgets.HBox([self.refresh_button, self.run_button]), self.status, self.logs, self.preview])
        self.refresh()

    def clear_saved_result(self):
        # Clear in-memory references only. Old files remain on disk.
        for name in ("result", "FINAL_PATH", "WORK_DIR", "CLEAN_HTML"):
            self.namespace[name] = None
        self.preview.clear_output()

    def refresh(self, _=None):
        if self.busy:
            return
        previous = self.choice.value
        files = sorted(path.resolve() for path in self.search_root.rglob("*")
                       if path.is_file() and path.suffix.lower() == ".docx") if self.search_root.is_dir() else []
        self.refreshing = True
        try:
            self.choice.options = [("— Chọn đề muốn đọc —", "")] + [(path.name + " — " + str(path.parent), str(path)) for path in files]
            self.choice.value = previous if previous in {str(path) for path in files} else ""
        finally:
            self.refreshing = False
        self.run_button.disabled = not bool(self.choice.value)
        if not self.choice.value:
            self.clear_saved_result()
            self.namespace["INPUT_DOCX"] = ""
            self.status.value = (f"Tìm thấy {len(files)} DOCX. <b>Chọn đề muốn đọc</b>; chưa chạy OCR." if files else
                                 "Chưa có DOCX trong Input. Thêm file vào Input rồi bấm Làm mới danh sách.")

    def on_choose(self, change):
        if self.busy or self.refreshing:
            return
        self.clear_saved_result()
        self.namespace["INPUT_DOCX"] = change["new"]
        self.run_button.disabled = not bool(change["new"])
        if change["new"]:
            self.status.value = "<b>Đã chọn, chưa chạy:</b> " + html.escape(Path(change["new"]).name)
        else:
            self.status.value = "Chưa chọn đề."

    def log_print(self, *args, sep=" ", end="\n", file=None, flush=False):
        if file is not None:
            return builtins.print(*args, sep=sep, end=end, file=file, flush=flush)
        self.logs.append_stdout(sep.join(map(str, args)) + end)

    def render_result(self, result, source):
        self.preview.append_display_data(HTML("<h3>Kết quả của: " + html.escape(source.name) + "</h3>"))
        for key, mime, label in (("html", "text/html", "Tải HTML để xem / in"),
                                 ("final", "text/markdown", "Tải Markdown"), ("archive", "application/zip", "Tải ZIP")):
            path = Path(result[key])
            if path.stat().st_size <= 10_000_000:
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                self.preview.append_display_data(HTML('<p><a download="' + html.escape(path.name) + '" href="data:' + mime + ';base64,' + encoded + '">' + label + '</a></p>'))
            else:
                self.preview.append_display_data(FileLink(str(path), result_html_prefix=label + ": "))
        page = Path(result["html"]).read_text(encoding="utf-8")
        self.preview.append_display_data(IFrame("about:blank", width="100%", height=1000, extras=[
            'title="Kết quả của ' + html.escape(source.name, quote=True) + '"',
            'sandbox="allow-scripts allow-modals allow-downloads"', 'srcdoc="' + html.escape(page, quote=True) + '"']))
        timing = result.get("metrics", {})
        seconds = timing.get("total_s", timing.get("total_before_zip_s"))
        if seconds is not None:
            self.preview.append_stdout(f"Tổng thời gian: {seconds:.2f}s ({seconds/60:.2f} phút)\n")

    def on_run(self, _=None):
        if self.busy or not self.choice.value:
            return
        source = Path(self.choice.value).resolve()
        self.clear_saved_result()
        self.logs.clear_output()
        self.namespace["INPUT_DOCX"] = str(source)
        self.busy = True
        for control in (self.choice, self.refresh_button, self.run_button):
            control.disabled = True
        self.run_button.description = "Đang đọc đề đã chọn…"
        self.status.value = "<b>ĐANG ĐỌC:</b> " + html.escape(source.name) + "<br>" + html.escape(str(source))
        missing = object()
        old_print = getattr(self.runner, "print", missing)
        self.runner.print = self.log_print
        started = time.monotonic()
        try:
            source = self.runner.validate_docx(source)
            result = self.runner.run(source, self.namespace.get("RUN_ROOT", "/kaggle/working/hybrid_original_fixed"),
                                     ocr_diagrams=bool(self.namespace.get("OCR_DIAGRAMS", False)),
                                     ocr_small_images=bool(self.namespace.get("OCR_SMALL_IMAGES", True)))
            if not isinstance(result, dict) or not result.get("results") or not result.get("html"):
                raise RuntimeError("Lượt chạy chưa trả về kết quả hoàn chỉnh.")
            copied_input = Path(result["results"]) / "input.docx"
            if not copied_input.is_file() or hashlib.sha256(copied_input.read_bytes()).digest() != hashlib.sha256(source.read_bytes()).digest():
                raise RuntimeError("Không hiển thị: file DOCX của kết quả không khớp đề đã chọn. Đã chặn kết quả cũ.")
            self.render_result(result, source)
            result["source_path"] = str(source)
            self.namespace.update(result=result, FINAL_PATH=result["final"], WORK_DIR=result["results"])
            self.status.value = "<b>ĐÃ XONG:</b> " + html.escape(source.name) + f" · {time.monotonic()-started:.1f}s. Kết quả mới ở bên dưới."
        except (Exception, KeyboardInterrupt) as error:
            self.clear_saved_result()
            self.status.value = "<b>CHƯA ĐỌC ĐƯỢC:</b> " + html.escape(source.name) + "<br>" + html.escape(str(error))
            self.logs.append_stderr(traceback.format_exc())
        finally:
            if old_print is missing:
                delattr(self.runner, "print")
            else:
                self.runner.print = old_print
            self.busy = False
            self.choice.disabled = self.refresh_button.disabled = False
            self.run_button.disabled = not bool(self.choice.value)
            self.run_button.description = "Đọc đề đã chọn"


def show_exam_picker(namespace, runner=None, search_root="/kaggle/input"):
    picker = ExamPicker(namespace, runner, search_root)
    display(picker.view)
    return picker


if __name__ == "__main__":
    exam_picker = show_exam_picker(globals())
