"""Disposable memory-only parser. Invoked over stdin/stdout, never with a stored file."""
import base64
from io import BytesIO
import json
import sys
from zipfile import ZipFile

MAX_TEXT = 24000
MAX_CELLS = 10000


def parse(name: str, data: bytes) -> dict:
    suffix = name.rsplit(".", 1)[-1].lower()
    text = []
    images = []
    image_labels = []
    if suffix == "xlsx":
        from openpyxl import load_workbook
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or sum(i.file_size for i in entries) > 20 * 1024 * 1024:
                raise ValueError("Workbook expanded size exceeds the safety limit.")
            if any(i.filename.endswith("vbaProject.bin") for i in entries):
                raise ValueError("Macro workbooks are not supported.")
        # Formula strings are never instructions or executable code. Uncached values remain explicitly missing.
        book = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
        cached = load_workbook(BytesIO(data), read_only=True, data_only=True, keep_links=False)
        cells = 0
        chars = 0
        try:
            if len(book.worksheets) > 20:
                raise ValueError("Use a workbook with at most 20 sheets.")
            for sheet in book:
                text.append(f"Sheet: {sheet.title}")
                if sheet.max_row and sheet.max_column and sheet.max_row * sheet.max_column > MAX_CELLS:
                    raise ValueError("Use a workbook with at most 10,000 cells.")
                # Exporters can leave stale dimension metadata. Read actual rows and enforce the
                # cell budget below, rather than silently truncating the financial data to that range.
                sheet.reset_dimensions()
                cached[sheet.title].reset_dimensions()
                for row, cached_row in zip(sheet, cached[sheet.title]):
                    cells += len(row)
                    if cells > MAX_CELLS:
                        raise ValueError("Use a workbook with at most 10,000 cells.")
                    values = []
                    for cell, cached_cell in zip(row, cached_row):
                        value = cached_cell.value if cell.data_type == "f" else cell.value
                        if cell.data_type == "f" and value is None:
                            values.append("[uncached formula; provide values]")
                        else:
                            values.append(str(value) if value is not None else "")
                    line = " | ".join(values)
                    chars += len(line) + 1
                    if chars > MAX_TEXT:
                        raise ValueError("Workbook has too much text. Attach a smaller selection.")
                    text.append(line)
        finally:
            book.close()
            cached.close()
    elif suffix == "pdf":
        import fitz
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                raise ValueError("Unlock the PDF before attaching it.")
            if not 0 < len(doc) <= 10:
                raise ValueError("Attach a PDF with at most 10 pages.")
            for i, page in enumerate(doc):
                page_text = page.get_text()
                # Include pages with raster content as well, so mixed text/scan PDFs aren't silently incomplete.
                if not page_text.strip() or page.get_images():
                    rect = page.rect
                    zoom = min(1.5, (2_000_000 / max(rect.width * rect.height, 1)) ** .5)
                    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB, alpha=False)
                    images.append(base64.b64encode(pix.tobytes("jpeg", jpg_quality=80)).decode())
                    image_labels.append(f"Page {i + 1}")
                else:
                    text.append(f"Page {i + 1}:\n{page_text}")
    elif suffix in {"jpg", "jpeg", "heic"}:
        from PIL import Image, ImageOps
        if suffix == "heic":
            from pillow_heif import register_heif_opener
            register_heif_opener()
        Image.MAX_IMAGE_PIXELS = 20_000_000
        with Image.open(BytesIO(data)) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError("Image exceeds the 20 megapixel safety limit.")
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("Attach a single-frame image.")
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((1800, 1800))
            out = BytesIO()
            image.save(out, "JPEG", quality=85)
            images.append(base64.b64encode(out.getvalue()).decode())
            image_labels.append("Image")
    else:
        raise ValueError("Unsupported attachment type.")
    joined = "\n".join(text)
    if len(joined) > MAX_TEXT:
        raise ValueError("File has too much text. Attach a smaller selection.")
    return {"text": joined, "images": images, "image_labels": image_labels}


def main():
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    try:
        request = json.loads(sys.stdin.buffer.read(8 * 1024 * 1024))
        result = parse(request["name"], base64.b64decode(request["data"], validate=True))
    except Exception:
        # Never print parser exceptions: some contain workbook cells or document contents.
        result = {"error": "File could not be read within the safety limits. Use an unlocked PDF of up to 10 pages, "
                  "a workbook of up to 10,000 cells, or a single image up to 20 megapixels."}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
