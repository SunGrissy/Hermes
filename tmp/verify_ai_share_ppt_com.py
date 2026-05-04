from pathlib import Path
import win32com.client

pptx = str(Path(r"D:/MyAgents/会议材料/驯化野生硅基伙伴_渐进披露版.pptx"))
app = win32com.client.Dispatch('PowerPoint.Application')
app.Visible = True
pres = app.Presentations.Open(pptx, WithWindow=False)
try:
    print('SLIDES', pres.Slides.Count)
    total = 0
    bad = []
    for slide in pres.Slides:
        seq = slide.TimeLine.MainSequence
        effects = seq.Count
        trigger_counts = {}
        names = []
        for i in range(1, effects + 1):
            eff = seq.Item(i)
            trig = eff.Timing.TriggerType
            trigger_counts[trig] = trigger_counts.get(trig, 0) + 1
            try:
                names.append(eff.Shape.Name)
            except Exception:
                names.append('?')
        total += effects
        print(f'SLIDE {slide.SlideIndex:02d}: effects={effects} triggers={trigger_counts} first={names[:5]}')
        if slide.SlideIndex > 1 and effects == 0:
            bad.append(slide.SlideIndex)
    print('TOTAL_EFFECTS', total)
    print('NO_EFFECT_SLIDES_AFTER_COVER', bad)
    assert pres.Slides.Count == 18
    assert total >= 45
    assert not bad
finally:
    pres.Close()
    app.Quit()
