from pathlib import Path
import zipfile
import re
import xml.etree.ElementTree as ET

pptx = Path(r"D:/MyAgents/会议材料/驯化野生硅基伙伴_渐进披露版.pptx")
assert pptx.exists(), f"missing {pptx}"

out = []
with zipfile.ZipFile(pptx, 'r') as z:
    slide_files = sorted([n for n in z.namelist() if re.match(r'ppt/slides/slide\d+\.xml$', n)], key=lambda n: int(re.search(r'slide(\d+)\.xml', n).group(1)))
    anim_files = [n for n in z.namelist() if re.match(r'ppt/slides/slide\d+\.xml$', n)]
    out.append(f"SLIDE_COUNT {len(slide_files)}")
    assert len(slide_files) == 18, len(slide_files)
    total_click = 0
    total_anim_nodes = 0
    no_anim = []
    titles = []
    for sf in slide_files:
        xml = z.read(sf).decode('utf-8', errors='ignore')
        idx = int(re.search(r'slide(\d+)\.xml', sf).group(1))
        texts = re.findall(r'<a:t>(.*?)</a:t>', xml)
        text_join = ''.join(texts)
        titles.append((idx, text_join[:80]))
        click_count = xml.count('onClick="1"') + xml.count('evt="onClick"') + xml.count('<p:cond')
        # PowerPoint stores animation in timing nodes: cTn/presetClass/entr effects.
        anim_count = xml.count('<p:timing') + xml.count('<p:animEffect') + xml.count('presetID="10"') + xml.count('entr')
        # More direct reveal count: shape target references inside timing tree.
        sp_tgt = xml.count('<p:spTgt')
        total_click += xml.count('onClick="1"')
        total_anim_nodes += sp_tgt
        if idx > 1 and sp_tgt == 0:
            no_anim.append(idx)
        on_click = xml.count('onClick="1"')
        out.append(f"SLIDE {idx:02d}: chars={len(text_join)} spTgt={sp_tgt} onClick={on_click} timing={'yes' if '<p:timing' in xml else 'no'}")
        assert '<p:timing' in xml or idx == 1, f"slide {idx} missing timing"
    must = ['驯化野生', '确定性硅基', '概率性硅基', 'Vibe Coding', '真正的钉子', '找一颗真实钉子']
    all_xml = ''.join(z.read(sf).decode('utf-8', errors='ignore') for sf in slide_files)
    for m in must:
        ok = m in all_xml
        out.append(f"KEYWORD {m}: {ok}")
        assert ok, m
    out.append(f"TOTAL_SHAPE_TARGETS {total_anim_nodes}")
    out.append(f"NO_ANIM_SLIDES_AFTER_COVER {no_anim}")
    assert total_anim_nodes >= 45, total_anim_nodes
    assert not no_anim, no_anim

print('\n'.join(out))
