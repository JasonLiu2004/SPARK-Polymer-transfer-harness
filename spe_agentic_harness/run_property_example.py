"""Run a labelled arithmetic example without API keys or simulation packages."""
import json
from datetime import datetime
from pathlib import Path
from harness import ResearchHarness

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    output = root / 'outputs' / ('property_example_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    h = ResearchHarness(output)
    request = json.loads((root / 'examples' / 'transport_example.json').read_text(encoding='utf-8'))
    result = h.execute('predict_conductivity', request)
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'artifact': str(output / 'result.json'), 'result': result}, ensure_ascii=False, indent=2))
