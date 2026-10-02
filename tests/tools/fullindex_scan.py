"""Stage 4 probe (NOT run in CI; network + SEC_USER_AGENT): every quarterly EDGAR full-index
form.gz from 1993 QTR1 to the current quarter, downloaded whole (store=False, nothing kept).

  python tests/tools/fullindex_scan.py <cache dir outside the repo> reports/artifacts/fullindex_verify.json

Checks what managers.EdgarDirectory relies on: data lines sorted by form type (pairs out of
order), where the 13F block is complete (compressed offset, in 64 KiB steps), counts of
13F-HR/HR-A/NT/NT-A, date format, CIK/date token positions; and the number of distinct CIKs
with any of the four forms."""
import gzip, json, re, sys, time, zlib, pathlib, collections, datetime as dt
from edgar13f.sec_client import SecClient
from edgar13f import config
sp = pathlib.Path(sys.argv[1]); out = pathlib.Path(sys.argv[2])
c = SecClient(sp, config.user_agent())
FORMS = {"13F-HR", "13F-HR/A", "13F-NT", "13F-NT/A"}
today = dt.date.today()
res = []
first_dates = {}
for y in range(1993, today.year + 1):
    for q in range(1, 5):
        if dt.date(y, 3 * q - 2, 1) > today: break
        url = f"https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.gz"
        t = time.perf_counter()
        b = c.get(url, store=False)
        dl = time.perf_counter() - t
        if b is None:
            res.append({"q": f"{y}Q{q}", "status": 404}); continue
        # streaming decompress to find compressed offset at which the 13F block is complete
        d = zlib.decompressobj(16 + zlib.MAX_WBITS); buf = b""; done_at = None; pos = 0
        while pos < len(b) and done_at is None:
            buf += d.decompress(b[pos:pos + 65536]); pos += 65536
            sep = buf.find(b"\n---")
            if sep < 0: continue
            body = buf[buf.find(b"\n", sep + 1) + 1:]
            for line in body.split(b"\n")[:-1]:
                ft = re.split(rb"\s{2,}", line.strip())[0] if line.strip() else b""
                if ft > b"13F-NT/A" and not ft.startswith(b"13F-"):
                    done_at = pos; break
        txt = gzip.decompress(b)
        sep = txt.find(b"\n---"); body = txt[txt.find(b"\n", sep + 1) + 1:]
        lines = [l for l in body.split(b"\n") if l.strip()]
        fts = [re.split(rb"\s{2,}", l.strip())[0] for l in lines]
        unsorted = sum(1 for a, b2 in zip(fts, fts[1:]) if b2 < a)
        cnt = collections.Counter(); badtok = 0; datefmt = collections.Counter()
        for l, ft in zip(lines, fts):
            if ft.decode() in FORMS:
                tok = l.split()
                cik, date = tok[-3].decode(), tok[-2].decode()
                cnt[ft.decode()] += 1
                datefmt["iso" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else date[:12]] += 1
                if not cik.isdigit(): badtok += 1
                else:
                    k = str(int(cik))
                    if k not in first_dates or date < first_dates[k]: first_dates[k] = date
        r = {"q": f"{y}Q{q}", "gz_bytes": len(b), "raw_bytes": len(txt), "dl_s": round(dl, 2), "lines": len(lines),
             "unsorted_pairs": unsorted, "block_done_at_gz_byte": done_at, "counts": dict(cnt),
             "bad_cik_tokens": badtok, "date_formats": dict(datefmt)}
        res.append(r); print(json.dumps(r), flush=True)
out.write_text(json.dumps({"quarters": res, "distinct_13f_ciks": len(first_dates)}, indent=1))
print("distinct ciks", len(first_dates))
