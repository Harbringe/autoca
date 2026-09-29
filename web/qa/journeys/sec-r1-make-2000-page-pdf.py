# Writes web/qa/samples/qa-sec-2000pages.pdf: 2,000 plain text pages, about 317 KB. Run from E:\autoca\web.
N = 2000
objs = ["<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [" + " ".join(f"{5+i} 0 R" for i in range(N)) + f"] /Count {N} >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
lines = ["BT /F1 10 Tf 40 780 Td 14 TL"] + [f"(QA SEC synthetic filler line {i} 01-04-2025 Payment 1000.00 2000.00) '" for i in range(45)] + ["ET"]
stream = "\n".join(lines)
objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
objs += ["<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 3 0 R >> >> >>"] * N
out = bytearray(b"%PDF-1.4\n"); offs = []
for i, o in enumerate(objs, 1):
    offs.append(len(out)); out += f"{i} 0 obj\n{o}\nendobj\n".encode()
x = len(out)
out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
for o in offs: out += f"{o:010d} 00000 n \n".encode()
out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
open("qa/samples/qa-sec-2000pages.pdf", "wb").write(out)
