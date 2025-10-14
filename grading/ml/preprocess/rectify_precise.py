from __future__ import annotations
import numpy as np, cv2 as cv

ASPECT = 88.0/63.0  # long/short

def _order_pts(pts: np.ndarray) -> np.ndarray:
    s = pts.sum(axis=1); d = np.diff(pts, axis=1).reshape(-1)
    tl = pts[np.argmin(s)]; br = pts[np.argmax(s)]
    tr = pts[np.argmin(d)]; bl = pts[np.argmax(d)]
    return np.array([tl, tr, br, bl], np.float32)

def _refine_edge(image_gray: np.ndarray, p0: np.ndarray, p1: np.ndarray, half_thickness: int=6) -> np.ndarray:
    """
    Slide a strip orthogonal to the initial edge; pick the line with max gradient magnitude.
    Returns 2 refined endpoints (float32).
    """
    v = p1 - p0; L = np.linalg.norm(v); 
    if L < 1: return np.stack([p0, p1], 0)
    v = v / L
    n = np.array([-v[1], v[0]], np.float32)  # outward normal

    # sample positions across ±half_thickness
    samples = []
    for t in range(-half_thickness, half_thickness+1):
        offset = n * t
        # sample along the edge as a polyline and get gradient magnitude
        xs = np.linspace(p0[0]+offset[0], p1[0]+offset[0], num=int(L))
        ys = np.linspace(p0[1]+offset[1], p1[1]+offset[1], num=int(L))
        xs = np.clip(xs, 0, image_gray.shape[1]-1)
        ys = np.clip(ys, 0, image_gray.shape[0]-1)
        vals = image_gray[ys.astype(np.int32), xs.astype(np.int32)]
        # edge strength = sum |d/ds|
        strength = float(np.abs(np.diff(vals.astype(np.float32))).sum())
        samples.append((strength, t))
    # choose the offset with max strength
    best_t = max(samples)[1]
    best_offset = n * best_t
    return np.stack([p0+best_offset, p1+best_offset], 0)

def precise_rectify(bgr: np.ndarray, target_min_side: int=1200) -> np.ndarray | None:
    """
    1) find biggest rectangular-ish contour
    2) fit min-area rectangle
    3) refine all four edges to the strongest gradient ridge (true border)
    4) warp to canonical 63×88 aspect at high resolution.
    """
    h, w = bgr.shape[:2]
    g = cv.cvtColor(bgr, cv.COLOR_BGR2GRAY)
    g = cv.GaussianBlur(g, (5,5), 0)
    edges = cv.Canny(g, 60, 160); edges = cv.dilate(edges, np.ones((3,3), np.uint8), 1)

    cnts, _ = cv.findContours(edges, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    if not cnts: return None
    cnt = max(cnts, key=cv.contourArea)
    if cv.contourArea(cnt) < 0.05*w*h:  # too small
        return None

    rect = cv.minAreaRect(cnt)
    box = cv.boxPoints(rect).astype(np.float32)
    box = _order_pts(box)

    # refine each edge on gradient image
    g_blurred = cv.GaussianBlur(g, (3,3), 0)
    E0 = _refine_edge(g_blurred, box[0], box[1])
    E1 = _refine_edge(g_blurred, box[1], box[2])
    E2 = _refine_edge(g_blurred, box[2], box[3])
    E3 = _refine_edge(g_blurred, box[3], box[0])

    # intersection of consecutive refined edges → 4 corner pts
    def line(p, q):
        a = q - p; return np.array([a[1], -a[0], a[0]*p[1]-a[1]*p[0]], np.float32)  # ax+by+c=0
    def intersect(L1, L2):
        a1,b1,c1 = L1; a2,b2,c2 = L2
        d = a1*b2 - a2*b1
        if abs(d) < 1e-6: return np.array([0,0], np.float32)
        x = (b1*c2 - b2*c1)/d; y = (c1*a2 - c2*a1)/d
        return np.array([x,y], np.float32)

    L0,L1,L2,L3 = map(lambda e: line(e[0], e[1]), (E0,E1,E2,E3))
    pts = np.stack([intersect(L0,L1), intersect(L1,L2), intersect(L2,L3), intersect(L3,L0)], 0)

    # decide destination size honoring aspect
    # ensure long side corresponds to 88
    side_w = max(np.linalg.norm(pts[1]-pts[0]), np.linalg.norm(pts[3]-pts[2]))
    side_h = max(np.linalg.norm(pts[2]-pts[1]), np.linalg.norm(pts[0]-pts[3]))
    if side_h >= side_w:
        dst_h = max(target_min_side, int(side_h))
        dst_w = int(dst_h / ASPECT)
    else:
        dst_w = max(target_min_side, int(side_w))
        dst_h = int(dst_w * ASPECT)

    dst = np.array([[0,0],[dst_w-1,0],[dst_w-1,dst_h-1],[0,dst_h-1]], np.float32)
    M = cv.getPerspectiveTransform(_order_pts(pts), dst)
    return cv.warpPerspective(bgr, M, (dst_w, dst_h), flags=cv.INTER_CUBIC)
