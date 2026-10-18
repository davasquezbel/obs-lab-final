"""Inserta la portada del estudiante (XML original, intacto) en el documento APA generado.

Único ajuste: los anchos fijos de las tablas de la portada se escalan al nuevo ancho
útil (márgenes APA de 1": 9360 DXA en vez de 10080), para que no se salgan de la página.
Uso: python3 merge_cover.py <cuerpo.docx> <cover.xml> <salida.docx>
"""
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

body_docx, cover_xml, out_docx = sys.argv[1:4]
OLD_W, NEW_W = 10080, 9360

cover = Path(cover_xml).read_text(encoding="utf8")


def scale(m):
    # Solo se reduce lo que no cabe en el nuevo ancho útil; lo demás queda intacto
    attr, val = m.group(1), int(m.group(2))
    return f'{attr}"{round(val * NEW_W / OLD_W) if val > NEW_W else val}"'


# Escalar solo anchos en DXA de tablas/celdas/columnas de la portada
cover = re.sub(r'(<w:tblW w:w=)"(\d+)"', scale, cover)
cover = re.sub(r'(<w:gridCol w:w=)"(\d+)"', scale, cover)
cover = re.sub(r'(<w:tcW w:w=)"(\d+)"', scale, cover)

tmp = Path(tempfile.mkdtemp())
with zipfile.ZipFile(body_docx) as z:
    z.extractall(tmp)
doc_path = tmp / "word" / "document.xml"
doc = doc_path.read_text(encoding="utf8")

# Reemplazar el párrafo marcador (docx-js pone el sectPr de la sección 1 en el último párrafo de esa sección)
m = re.search(r'<w:p>(?:(?!<w:p>).)*?§§PORTADA§§.*?</w:p>', doc, re.S)
assert m, "marcador no encontrado"
marker = m.group(0)
sect = re.search(r'<w:sectPr.*?</w:sectPr>', marker, re.S)
replacement = cover
if sect:  # conservar el salto de sección de la portada
    replacement += f'<w:p><w:pPr>{sect.group(0)}</w:pPr></w:p>'
doc = doc.replace(marker, replacement)

# Namespaces usados por la portada (Word 2010+)
root = re.search(r'<w:document[^>]*>', doc).group(0)
needed = {
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "w15": "http://schemas.microsoft.com/office/word/2012/wordml",
}
new_root = root
for prefix, uri in needed.items():
    if f"xmlns:{prefix}=" not in new_root:
        new_root = new_root.replace("<w:document", f'<w:document xmlns:{prefix}="{uri}"', 1)
if "mc:Ignorable" not in new_root:
    new_root = new_root.replace(">", ' mc:Ignorable="w14 w15">', 1)
doc = doc.replace(root, new_root, 1)
doc_path.write_text(doc, encoding="utf8")

out = Path(out_docx)
if out.exists():
    out.unlink()
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(tmp.rglob("*")):
        if f.is_file():
            z.write(f, f.relative_to(tmp).as_posix())
shutil.rmtree(tmp)
print("OK", out, "| portada:", len(cover), "bytes", "| sectPr conservado:", bool(sect))
