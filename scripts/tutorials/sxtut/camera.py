"""The v2 camera: zooms toward what is tapped or highlighted, as ffmpeg zoompan expressions.

A camera state is (zoom, centre x, centre y) in source pixels. A beat's camera is a list of
keyframes (seconds into the beat, state); between keyframes the move eases (smoothstep). Moves
are short (about half a second) and the camera holds still in between, which hides zoompan's
whole-pixel steps.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class State:
    z: float
    cx: float
    cy: float


def full(w: int, h: int) -> State:
    return State(1.0, w / 2, h / 2)


def focus(
    box: dict, w: int, h: int, zmax: float, fill_w: float = 0.62, fill_h: float = 0.42
) -> State | None:
    """The state that frames `box` ({x, y, w, h} in source px) with room around it, or None when the
    box is already big on screen (less than a 1.15x zoom would help)."""
    bw, bh = max(box["w"], 1), max(box["h"], 1)
    z = min(zmax, w * fill_w / bw, h * fill_h / bh)
    if z < 1.15:
        return None
    win_w, win_h = w / z, h / z
    cx = min(max(box["x"] + bw / 2, win_w / 2), w - win_w / 2)
    cy = min(max(box["y"] + bh / 2, win_h / 2), h - win_h / 2)
    return State(round(z, 4), round(cx, 1), round(cy, 1))


def at(keys: list[tuple[float, State]], t: float) -> State:
    """The camera state at time t, eased between keyframes as the zoompan expression does."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, a), (t1, b) in zip(keys, keys[1:], strict=False):
        if t < t1:
            u = min(max((t - t0) / max(t1 - t0, 1e-3), 0.0), 1.0)
            s = u * u * (3 - 2 * u)
            return State(a.z + (b.z - a.z) * s, a.cx + (b.cx - a.cx) * s, a.cy + (b.cy - a.cy) * s)
    return keys[-1][1]


def on_screen(box: dict, st: State, w: int, h: int, out_w: int, out_h: int) -> tuple[float, ...]:
    """Where a source box lands in the output picture (x, y, w, h) under camera state st."""
    win_w, win_h = w / st.z, h / st.z
    x0 = min(max(st.cx - win_w / 2, 0.0), w - win_w)
    y0 = min(max(st.cy - win_h / 2, 0.0), h - win_h)
    sx, sy = out_w / win_w, out_h / win_h
    return ((box["x"] - x0) * sx, (box["y"] - y0) * sy, box["w"] * sx, box["h"] * sy)


def _num(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def expr(keys: list[tuple[float, float]], t: str = "T") -> str:
    """Piecewise smoothstep through (time, value) keyframes (in time order) as an ffmpeg expression
    in `t`."""
    if len(keys) == 1 or all(v == keys[0][1] for _, v in keys):
        return _num(keys[0][1])
    out = _num(keys[-1][1])
    for (t0, v0), (t1, v1) in reversed(list(zip(keys, keys[1:], strict=False))):
        if v0 == v1:
            seg = _num(v0)
        else:
            span = max(t1 - t0, 1e-3)
            u = f"clip(({t}-{_num(t0)})/{_num(span)},0,1)"
            seg = f"({_num(v0)}+({_num(v1 - v0)})*{u}*{u}*(3-2*{u}))"
        out = f"if(lt({t},{_num(t1)}),{seg},{out})"
    first_t, first_v = keys[0]
    return f"if(lt({t},{_num(first_t)}),{_num(first_v)},{out})"


def zoompan(
    keys: list[tuple[float, State]], in_w: int, in_h: int, out_w: int, out_h: int, fps: int = 30
) -> str:
    """A zoompan filter (one output frame per input frame) following the keyframes."""
    t = f"on/{fps}"
    z = expr([(k, s.z) for k, s in keys], t)
    cx = expr([(k, s.cx) for k, s in keys], t)
    cy = expr([(k, s.cy) for k, s in keys], t)
    x = f"max(0,min(iw-iw/zoom,({cx})-iw/zoom/2))"
    y = f"max(0,min(ih-ih/zoom,({cy})-ih/zoom/2))"
    return f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={out_w}x{out_h}:fps={fps}"


def plan(
    dur: float,
    events: list[tuple[float, str, State | None]],
    start: State,
    rest: State,
    end: State | None,
    ease_in: float = 0.45,
    ease_out: float = 0.5,
) -> list[tuple[float, State]]:
    """Keyframes for one beat of `dur` seconds.

    events: (time in the beat, kind, focus state or None) in time order. A focus state zooms there,
    arriving at the event; a tap is followed by a return to `rest` (the screen usually changes); an
    event without a state (a scroll, a new screen) returns to `rest` before it. `end` is the
    state to finish in (None: stay where the beat leaves the camera, the next beat carries on
    from there).
    The last keyframe's state is where the camera really ends (a move with no room is skipped)."""
    keys: list[tuple[float, State]] = [(0.0, start)]
    cur, t_free = start, 0.0

    def move(at: float, to: State, ease: float) -> None:
        nonlocal cur, t_free
        if to == cur:
            return
        at = min(at, dur)
        a = max(t_free, at - ease)
        b = max(a + 0.25, at)
        if b > dur:
            a, b = max(t_free, dur - 0.25), dur
            if b - a < 0.15:
                return
        keys.append((a, cur))
        keys.append((b, to))
        cur, t_free = to, b

    for at, kind, st in events:
        if st is not None:
            move(at + 0.08, st, ease_in)
            if kind == "tap":
                move(at + 0.35 + ease_out, rest, ease_out)
        else:
            move(at, rest, 0.35)
    if end is not None and end != cur:
        move(dur, end, ease_out)
    if keys[-1][0] < dur:
        keys.append((dur, cur))
    return keys
