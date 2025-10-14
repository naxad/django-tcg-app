# grading/ml/identify.py
import cv2 as cv, numpy as np, re
from pathlib import Path
import easyocr

_reader = easyocr.Reader(['en'], gpu=False)

def ocr_bottom_text(img_bgr):
    h,w = img_bgr.shape[:2]
    roi = img_bgr[int(h*0.88):int(h*0.98), int(w*0.05):int(w*0.95)]
    res = _reader.readtext(roi, detail=0)
    text = " ".join(res)
    num = re.search(r'\b(\d{1,3})\s*/\s*(\d{1,3})\b', text)
    code = re.search(r'\b[A-Z0-9]{2,5}\b', text)  # rough set code
    return (num.group(0) if num else None, code.group(0) if code else None)

def feature_match_identify(img_bgr, ref_dir: Path):
    # Build BFMatcher over ORB features across ref_dir of thumbnails
    orb = cv.ORB_create(1500)
    kp1, des1 = orb.detectAndCompute(cv.cvtColor(img_bgr, cv.COLOR_BGR2GRAY), None)
    best = (None, -1, None)
    for rp in ref_dir.glob("*.jpg"):
        ref = cv.imread(str(rp), cv.IMREAD_GRAYSCALE)
        kp2, des2 = orb.detectAndCompute(ref, None)
        if des1 is None or des2 is None: continue
        m = cv.BFMatcher(cv.NORM_HAMMING, crossCheck=True).match(des1, des2)
        m = sorted(m, key=lambda x: x.distance)[:80]
        if len(m) < 20: continue
        src = np.float32([kp1[k.queryIdx].pt for k in m]).reshape(-1,1,2)
        dst = np.float32([kp2[k.trainIdx].pt for k in m]).reshape(-1,1,2)
        H, mask = cv.findHomography(src, dst, cv.RANSAC, 3.0)
        inliers = int(mask.sum()) if mask is not None else 0
        if inliers > best[1]:
            best = (rp, inliers, H)
    return best  # (best_ref_path, inlier_count, H)
