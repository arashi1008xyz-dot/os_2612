"""Read a normalized amount JSON and export a city without running a web server."""
import argparse
import json
from pathlib import Path
import sys
from .config import load_config, read_json
from .core import RecordAmounts, calculate_city
from .render import render_html, render_svg


def main():
    parser = argparse.ArgumentParser(description="記録量JSONから街並みを生成します。元データは変更しません。")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--html", type=Path)
    parser.add_argument("--svg", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--theme", choices=("auto","light","dark"), default="auto")
    args = parser.parse_args()
    outputs = [p.resolve() for p in (args.html,args.svg,args.state) if p]
    if len(set(outputs)) != len(outputs) or args.input.resolve() in outputs:
        parser.error("入力ファイルと出力ファイルには、それぞれ異なるパスを指定してください。")
    try:
        amounts = RecordAmounts.from_mapping(read_json(args.input))
        config = load_config()
        state = calculate_city(amounts,config)
        result = json.dumps(state.to_dict(),ensure_ascii=False,indent=2)+'\n'
        if args.html:
            html = ('<!doctype html><html lang="ja"><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<title>あなたの街</title><style>html{color-scheme:light dark}body{margin:0;padding:20px;'
                    'font-family:system-ui,sans-serif;background:Canvas;color:CanvasText}</style>'
                    +render_html(state,config,theme=args.theme)+'</html>')
            args.html.write_text(html,encoding="utf-8")
        if args.svg:
            args.svg.write_text(render_svg(state,config,theme=args.theme),encoding="utf-8")
        if args.state:
            args.state.write_text(result,encoding="utf-8")
        sys.stdout.write(result)
    except (OSError,ValueError,KeyError,TypeError) as error:
        parser.exit(2,f"街の生成に失敗しました: {error}\n")


if __name__ == "__main__":
    main()
