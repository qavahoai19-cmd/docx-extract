"""Disposable ipywidgets interface for the separate benchmark notebook."""
import base64
import html

from runner import run_benchmark


def report_html(report):
    summary = report["summary"]
    labels = [("total_s", "Tổng thời gian (giây)"),
              ("server_prepare_s", "Chuyển/crop ảnh tại server (giây)"),
              ("server_infer_s", "Xử lý OCR tại server (giây)"),
              ("formulas", "Vị trí công thức MathType"),
              ("remote_images", "Ảnh gửi đến server"),
              ("http_requests", "Request OCR"), ("cache_hits", "Lượt lấy cache client"),
              ("failures", "Công thức chưa có kết quả"), ("failed_documents", "Đề lỗi")]
    rows = []
    for name, label in labels:
        values = []
        for mode in ("before", "after"):
            value = summary.get(mode, {}).get(name)
            values.append("—" if value is None else f"{value:.2f}" if name.endswith("_s") else str(value))
        rows.append(f"<tr><td>{label}</td><td>{values[0]}</td><td>{values[1]}</td></tr>")
    result = ('<table style="border-collapse:collapse" border="1" cellpadding="7">'
              '<tr><th>Chỉ số</th><th>Trước tối ưu</th><th>Sau tối ưu</th></tr>' + "".join(rows) + "</table>")
    if "observed_speedup" in report:
        valid = report["comparison_without_detected_differences"]
        status = "Không phát hiện khác biệt đầu ra trong phép đối chiếu." if valid else "CẦN KIỂM TRA: có lỗi hoặc khác biệt đầu ra; tỉ lệ thời gian chỉ để tham khảo."
        result += (f"<p><b>Tỉ lệ thời gian trước/sau: {report['observed_speedup']:.2f} lần; "
                   f"giảm {report['observed_reduction_percent']:.1f}%.</b><br>{status}</p>")
    result += ("<p>Cache kết quả TẮT ở cả hai phía. Model đã nạp và warm-up trước khi đo. "
               "Tổng thời gian gồm bóc Word, chuẩn bị ảnh, OCR, ghi kết quả và ZIP; "
               "không gồm upload, tải model hoặc đóng gói báo cáo. "
               "Đầu ra giống nhau chưa chứng minh công thức được OCR chính xác.</p>")
    health = report["health"]
    result += "<p>GPU batch thực tế: " + html.escape(str(health.get("inference_batch_size", "?")))
    result += "; kiểm tra batch: " + html.escape(str(health.get("batch_verified", False))) + ".</p>"
    return result


def show_benchmark_ui(root, endpoint):
    import ipywidgets as widgets
    from IPython.display import HTML, display
    from notebook_upload import upload_items

    upload = widgets.FileUpload(accept=".docx,.zip", multiple=True, description="Chọn đề/ZIP")
    repeat = widgets.Dropdown(options=[("Đo nhanh: 1 lượt", 1), ("Đo kỹ: 3 lượt, lấy trung vị", 3)], value=1)
    before = widgets.Button(description="Đo trước tối ưu", disabled=True, layout=widgets.Layout(width="180px"))
    after = widgets.Button(description="Đo sau tối ưu", disabled=True, layout=widgets.Layout(width="180px"))
    both = widgets.Button(description="Chạy cả hai và so sánh", button_style="success", disabled=True,
                          layout=widgets.Layout(width="220px"))
    output = widgets.Output()
    selected = widgets.HTML("Chọn cùng bộ đề cho phép so sánh. Mỗi lần bấm đều chạy OCR thật, không dùng cache.")
    buttons = (before, after, both)

    def changed(change):
        names = [name for name, _ in upload_items(change["new"])]
        selected.value = "Đã chọn: " + ", ".join(html.escape(name) for name in names) if names else "Chọn DOCX hoặc ZIP chứa DOCX."
        for button in buttons:
            button.disabled = not bool(names)

    def measure(modes):
        upload.disabled = repeat.disabled = True
        for button in buttons:
            button.disabled = True
        output.clear_output(wait=True)
        try:
            with output:
                print("Đo cả bộ đề. Hai bản dùng chung GPU/model; không chạy đồng thời. Có thể mất vài phút.", flush=True)
                report, archive = run_benchmark(list(upload_items(upload.value)), root, endpoint,
                    modes=modes, repetitions=repeat.value, progress=lambda message: print(message, flush=True))
                display(HTML(report_html(report)))
                encoded = base64.b64encode(archive.read_bytes()).decode("ascii")
                display(HTML(f'<a download="{html.escape(archive.name)}" href="data:application/zip;base64,{encoded}">'
                             'Tải báo cáo + kết quả hai bản (ZIP)</a>'))
                print("File cũng có trong Output:", archive)
        except Exception as exc:
            with output:
                print("Không hoàn tất benchmark:", exc)
        finally:
            upload.disabled = repeat.disabled = False
            for button in buttons:
                button.disabled = not bool(upload.value)

    upload.observe(changed, names="value")
    before.on_click(lambda _: measure(("before",)))
    after.on_click(lambda _: measure(("after",)))
    both.on_click(lambda _: measure(("before", "after")))
    display(widgets.VBox([widgets.HTML("<h3>So sánh OCR trước/sau tối ưu</h3>"), upload, selected,
                          repeat, widgets.HBox(list(buttons)), output]))
    return {"uploader": upload, "before": before, "after": after, "both": both, "output": output}
