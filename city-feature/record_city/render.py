"""Dependency-free SVG/HTML renderer. No JavaScript, filesystem writes, or app CSS."""
from html import escape
import base64
import math
from .config import CityConfig, load_config
from .core import CityState


def _fmt(value):
    return f"{value:,.1f}".rstrip("0").rstrip(".")


def render_svg(state: CityState, config: CityConfig | None = None, *, theme="auto"):
    config = config or load_config()
    if theme not in ("auto", "light", "dark"):
        raise ValueError("theme must be auto, light or dark")
    if state.plan_version != config.plan_version or state.max_buildings != config.max_buildings:
        raise ValueError("State and layout configuration do not match")
    svg = []
    def project(x, y, z=0):
        return (365 + (x-y)*.78, 245 + (x+y)*.45-z)
    def point_text(points):
        return " ".join(f"{u:.3f},{v:.3f}" for u,v in (project(*p) for p in points))
    def poly(points, color, *, extra=""):
        svg.append(f'<polygon points="{point_text(points)}" fill="var(--rc-{color})" {extra}/>')
    def line(a, b, color="frame", *, dashed=False):
        u,v = project(*a); r,s = project(*b)
        svg.append(f'<line x1="{u:.3f}" y1="{v:.3f}" x2="{r:.3f}" y2="{s:.3f}" '
                   f'stroke="var(--rc-{color})" stroke-width="1.2"'+(' stroke-dasharray="3 2"' if dashed else '')+'/>')
    def box(x,y,w,d,z,h,palette,windows=True,bands=False):
        poly([(x,y+d,z),(x+w,y+d,z),(x+w,y+d,z+h),(x,y+d,z+h)],palette+'-front')
        poly([(x+w,y,z),(x+w,y+d,z),(x+w,y+d,z+h),(x+w,y,z+h)],palette+'-side')
        poly([(x,y,z+h),(x+w,y,z+h),(x+w,y+d,z+h),(x,y+d,z+h)],palette+'-top')
        if not windows:
            return
        level=z+8
        while level < z+h-5:
            if bands:
                if w>7:
                    poly([(x+3,y+d,level),(x+w-3,y+d,level),(x+w-3,y+d,level+2),(x+3,y+d,level+2)],'window',extra='opacity=".7"')
                if d>7:
                    poly([(x+w,y+3,level),(x+w,y+d-3,level),(x+w,y+d-3,level+2),(x+w,y+3,level+2)],'window',extra='opacity=".6"')
            else:
                for xx in range(5,math.ceil(w-4),8):
                    poly([(x+xx,y+d,level),(x+xx+2.7,y+d,level),(x+xx+2.7,y+d,level+5),(x+xx,y+d,level+5)],'window',extra='opacity=".85"')
                for yy in range(5,math.ceil(d-4),8):
                    poly([(x+w,y+yy,level),(x+w,y+yy+2.7,level),(x+w,y+yy+2.7,level+5),(x+w,y+yy,level+5)],'window',extra='opacity=".8"')
            level += 11
    count = state.completed_visible + (state.current_building is not None)
    active = config.buildings[:count]
    label = f"水辺のビル街。{state.completed_visible}棟完成。{state.stage_label}。"
    svg.append('<svg xmlns="http://www.w3.org/2000/svg" class="rc-city-svg" viewBox="0 0 760 700" '
               'role="img" width="760" height="700" style="width:100%;height:auto;display:block" '
               f'aria-label="{escape(label,quote=True)}" data-plan="{escape(config.plan_version,quote=True)}">')
    svg.append(f'<title>{escape(label)}</title>')
    light = {"ground":"#f2f5f5","water":"#c7e8e8","frame":"#a5b4b4","window":"#eef8f7"}
    for palette, colors in config.palettes.items():
        light.update({f"{palette}-{face}":color for face,color in zip(("front","side","top"),colors)})
    dark = {**light,"ground":"#263535","water":"#285456","frame":"#8ca5a5","window":"#cbe8e5",
            "gray-front":"#647b7b","gray-side":"#4c6464","gray-top":"#92a3a3",
            "pale-front":"#548d8a","pale-side":"#3d7372","pale-top":"#8abbb8"}
    def tokens(palette):
        return ";".join(f"--rc-{key}:{value}" for key,value in palette.items())
    # SVG-local selectors; no host body, nav, input, or Streamlit element selectors.
    css=f'.rc-city-svg{{{tokens(dark if theme=="dark" else light)}}}'
    if theme=="auto":
        css += f'@media(prefers-color-scheme:dark){{.rc-city-svg{{{tokens(dark)}}}}}'
    svg.append('<style>'+css+'</style>')
    used_blocks = {p.block for p in active}
    for b in config.blocks:
        if b.id in used_blocks:
            poly([(b.x-1,b.y-1,0),(b.x+b.width+1,b.y-1,0),(b.x+b.width+1,b.y+b.depth+1,0),(b.x-1,b.y+b.depth+1,0)],'ground')
    poly([(-5,368,0),(453,368,0),(453,407,0),(-5,407,0)],'water')
    poly([(-5,363,1),(453,363,1),(453,368,1),(-5,368,1)],'gray-top')
    box(116,367,14,39,0,5,'gray',False)
    line((116,365,9),(116,407,9));line((130,365,9),(130,407,9))
    for p in sorted(active,key=lambda b:(b.x+b.y+b.width+b.depth,b.id)):
        complete = p.id <= state.completed_visible
        stage = "complete" if complete else state.stage
        svg.append(f'<g data-building-id="{p.id}" data-stage="{stage}" data-style="{escape(p.style,quote=True)}">')
        svg.append(f'<title>{p.id}棟目・{"完成" if complete else state.stage_label}</title>')
        if stage in ("empty","groundwork"):
            poly([(p.x,p.y,0),(p.x+p.width,p.y,0),(p.x+p.width,p.y+p.depth,0),(p.x,p.y+p.depth,0)],'ground')
            corners=[(p.x,p.y,0),(p.x+p.width,p.y,0),(p.x+p.width,p.y+p.depth,0),(p.x,p.y+p.depth,0)]
            for a,b in zip(corners,corners[1:]+corners[:1]): line(a,b,dashed=True)
            if stage=="groundwork":
                line(corners[0],corners[2]);line(corners[1],corners[3])
        elif stage=="foundation":
            box(p.x,p.y,p.width,p.depth,0,4,'gray',False)
        else:
            for v in p.volumes:
                x,y,w,d,z,h=p.x+v.x,p.y+v.y,v.width,v.depth,v.z,v.height
                if stage=="frame":
                    for xx in (x,x+w):
                        for yy in (y,y+d): line((xx,yy,z),(xx,yy,z+h))
                    for level in range(0,math.ceil(h),16):
                        line((x+w,y,z+level),(x+w,y+d,z+level));line((x,y+d,z+level),(x+w,y+d,z+level))
                    for a,b in [((x,y,z+h),(x+w,y,z+h)),((x+w,y,z+h),(x+w,y+d,z+h)),
                                ((x+w,y+d,z+h),(x,y+d,z+h)),((x,y+d,z+h),(x,y,z+h))]: line(a,b)
                else:
                    box(x,y,w,d,z,h,p.palette if complete else 'gray',complete,v.bands)
        svg.append('</g>')
    svg.append('</svg>')
    return ''.join(svg)


def render_html(state, config=None, *, theme="auto", show_summary=True, image_mode=False):
    """Embeddable fragment. Its only visual scope is .record-city-panel."""
    scene = render_svg(state, config, theme=theme)
    if image_mode:
        # Streamlit st.html sanitizes with USE_PROFILES={html: true}, removing
        # inline SVG. An HTML img preserves the SVG as a self-contained image.
        encoded = base64.b64encode(scene.encode("utf-8")).decode("ascii")
        scene = (f'<img src="data:image/svg+xml;base64,{encoded}" '
                 f'alt="水辺のビル街。{state.completed_visible}棟完成。{state.stage_label}。" '
                 'width="760" height="700" style="width:100%;height:auto;display:block"/>')
    if state.capped:
        status=f"{state.max_buildings}棟の街が完成しました"
    else:
        status=f"{state.completed_visible}棟完成 · {state.current_building}棟目は{state.stage_label}"
    summary = ''
    if show_summary:
        total_hours = state.total_minutes // 60
        total_rest = state.total_minutes % 60
        summary=f'<p class="rc-summary">累計 {_fmt(total_hours)}時間 {_fmt(total_rest)}分相当 · {status}</p>'
        if not state.capped:
            summary += (f'<progress max="1" value="{state.progress}" aria-label="次のビルの建築進捗"></progress>'
                        f'<p class="rc-note">完成まであと{_fmt(state.remaining_minutes)}分相当</p>')
    return ('<section class="record-city-panel"><style>'
            '.record-city-panel{max-width:760px;margin:0 auto;font-family:inherit;color:inherit}'
            '.record-city-panel h2{font-size:1.4rem;font-weight:500;margin:0 0 .4rem}'
            '.record-city-panel p{line-height:1.7;margin:.4rem 0;font-size:.9rem}'
            '.record-city-panel .rc-note{opacity:.75}'
            '.record-city-panel progress{width:100%;height:8px;accent-color:#399a9b}'
            '</style><h2>あなたの街</h2><p class="rc-note">記録の積み重ねが、街になる</p>'
            +scene+summary+'</section>')
