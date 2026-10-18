import json
import base64
from html.parser import HTMLParser
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from record_city import RecordAmounts, calculate_city, load_config, render_html, render_svg
from record_city.config import DATA

SVG = '{http://www.w3.org/2000/svg}'


class CityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load_config()

    def state(self, **values):
        return calculate_city(values, self.config)

    def test_equivalent_media(self):
        for key,value in [('book_pages',300),('manga_pages',1500),('anime_minutes',600),
                          ('movie_minutes',600),('drama_minutes',600)]:
            with self.subTest(key=key):
                state = self.state(**{key:value})
                self.assertEqual(state.total_minutes,600)
                self.assertEqual(state.completed_visible,1)
                self.assertEqual(state.stage,'empty')

    def test_mixed_amounts(self):
        state = self.state(book_pages=100,manga_pages=500,movie_minutes=120)
        self.assertEqual(state.total_minutes,520)
        self.assertEqual(state.remaining_minutes,80)

    def test_every_construction_boundary(self):
        for minutes,stage in [('0','empty'),('.01','groundwork'),('149.99','groundwork'),
                              ('150','foundation'),('299.99','foundation'),('300','frame'),
                              ('449.99','frame'),('450','shell'),('599.99','shell'),('600','empty')]:
            with self.subTest(minutes=minutes):
                self.assertEqual(self.state(anime_minutes=Decimal(minutes)).stage,stage)

    def test_fractional_manga_has_exact_boundary(self):
        self.assertEqual(self.state(manga_pages=1499).remaining_minutes,Decimal('.4'))
        self.assertEqual(self.state(manga_pages=1500).completed_visible,1)

    def test_small_fraction_never_rounds_up_to_completion(self):
        state=self.state(anime_minutes=Decimal('599.99999999999999999999999999999'))
        self.assertEqual(state.completed_visible,0)
        self.assertGreater(state.remaining_minutes,0)

    def test_display_cap_keeps_actual_total(self):
        before=self.state(anime_minutes=Decimal('71999.9'))
        at=self.state(anime_minutes=72000)
        after=self.state(anime_minutes=78001)
        self.assertEqual(before.completed_visible,119)
        self.assertEqual(before.current_building,120)
        self.assertFalse(before.capped)
        for state in (at,after):
            self.assertEqual(state.completed_visible,120)
            self.assertIsNone(state.current_building)
            self.assertEqual(state.stage,'complete')
            self.assertEqual(state.remaining_minutes,0)
        self.assertEqual(after.completed_total,130)
        self.assertEqual(after.total_minutes,78001)
        self.assertEqual(after.displayed_minutes,72000)
        self.assertEqual(render_svg(at,self.config),render_svg(after,self.config))

    def test_recalculation_handles_reduced_amount(self):
        self.state(anime_minutes=78000)
        state=self.state(anime_minutes=850)
        self.assertEqual(state.completed_visible,1)
        self.assertEqual(state.stage,'foundation')

    def test_invalid_amounts_are_not_silently_counted_as_zero(self):
        for value in (-1,True,None,'100',float('nan'),float('inf'),Decimal('-Infinity')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.state(book_pages=value)
        with self.assertRaises(ValueError): self.state(film_minutes=100)

    def test_master_plan_is_complete_diverse_and_has_no_lot_overlap(self):
        buildings=self.config.buildings
        self.assertEqual(len(buildings),120)
        self.assertEqual(len(self.config.blocks),20)
        self.assertEqual(len({b.style for b in buildings}),6)
        self.assertEqual(len({b.style for b in buildings[96:]}),6)
        self.assertGreater(len({(b.width,b.depth) for b in buildings}),30)
        for i,a in enumerate(buildings):
            for b in buildings[i+1:]:
                x=min(a.x+a.width,b.x+b.width)-max(a.x,b.x)
                y=min(a.y+a.depth,b.y+b.depth)-max(a.y,b.y)
                self.assertFalse(x>1e-5 and y>1e-5,f'Overlapping lots: {a.id}, {b.id}')

    def test_each_rendered_stage_is_valid_and_in_camera(self):
        for amount in (0,1,150,300,450,600,29130,57930,71999,72000,80000):
            with self.subTest(amount=amount):
                state=self.state(anime_minutes=amount)
                svg=ET.fromstring(render_svg(state,self.config))
                groups=svg.findall(f'{SVG}g')
                self.assertEqual(len(groups),min(120,state.completed_visible+1))
                self.assertEqual(sum(g.attrib['data-stage']=='complete' for g in groups),state.completed_visible)
                for polygon in svg.iter(f'{SVG}polygon'):
                    for pair in polygon.attrib['points'].split():
                        x,y=map(float,pair.split(','))
                        self.assertTrue(0<=x<=760 and 0<=y<=700,(amount,x,y))
                for line in svg.iter(f'{SVG}line'):
                    for k,maximum in [('x1',760),('x2',760),('y1',700),('y2',700)]:
                        self.assertTrue(0<=float(line.attrib[k])<=maximum)

    def test_existing_buildings_do_not_move_or_change(self):
        def groups(minutes):
            svg=ET.fromstring(render_svg(self.state(anime_minutes=minutes),self.config))
            return {g.attrib['data-building-id']:ET.tostring(g) for g in svg.findall(f'{SVG}g')}
        small,large=groups(28800),groups(72000)
        for identifier in map(str,range(1,49)):
            self.assertEqual(small[identifier],large[identifier])

    def test_json_files_remain_unchanged(self):
        before={p:p.read_bytes() for p in DATA.glob('*.json')}
        state=self.state(book_pages=50000)
        for theme in ('auto','light','dark'):
            self.assertIn('record-city-panel',render_html(state,self.config,theme=theme))
        self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_corrupt_settings_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'rules.json'
            data=json.loads((DATA/'rules.json').read_text(encoding='utf-8'))
            data['max_buildings']=121
            path.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaises(ValueError): load_config(rules_path=path)
            path.write_text('{broken',encoding='utf-8')
            with self.assertRaises(ValueError): load_config(rules_path=path)

    def test_streamlit_adapter_only_renders_feature(self):
        from record_city.streamlit_view import CITY_NAV_ITEM, render_city
        class Host:
            def __init__(self): self.calls=[]
            def html(self,text): self.calls.append(text)
        host=Host()
        with patch.dict(sys.modules,{'streamlit':host}):
            state=render_city({'book_pages':300},config=self.config)
        self.assertEqual(CITY_NAV_ITEM,('city','街'))
        self.assertEqual(state.completed_visible,1)
        self.assertEqual(len(host.calls),1)
        self.assertNotIn('<svg',host.calls[0])
        self.assertIn('<img src="data:image/svg+xml;base64,',host.calls[0])

    def test_streamlit_image_contains_the_complete_svg(self):
        class Images(HTMLParser):
            sources=[]
            def handle_starttag(self,tag,attrs):
                if tag=='img': self.sources.append(dict(attrs)['src'])
        state=self.state(anime_minutes=72000)
        parser=Images()
        parser.feed(render_html(state,self.config,image_mode=True))
        self.assertEqual(len(parser.sources),1)
        image=base64.b64decode(parser.sources[0].split(',',1)[1])
        svg=ET.fromstring(image)
        self.assertEqual(len(svg.findall(f'{SVG}g')),120)

    def test_cli_exports_and_protects_its_input(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);source=folder/'amounts.json'
            source.write_text('{"movie_minutes": 78000}',encoding='utf-8')
            result=subprocess.run([sys.executable,'-m','record_city','--input',str(source),
                                   '--html',str(folder/'city.html'),'--state',str(folder/'state.json')],
                                  cwd=Path(__file__).resolve().parents[1],capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['completed_visible'],120)
            self.assertTrue((folder/'city.html').exists())
            bad=subprocess.run([sys.executable,'-m','record_city','--input',str(source),
                                '--state',str(source)],cwd=Path(__file__).resolve().parents[1],capture_output=True)
            self.assertNotEqual(bad.returncode,0)
            self.assertEqual(source.read_text(),'{"movie_minutes": 78000}')


if __name__=='__main__':
    unittest.main()
