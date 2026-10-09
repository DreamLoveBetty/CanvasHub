"""Fail closed on silent vendor model-name fallback, even if output was produced."""
import re


class ModelEvidence:
    def __init__(self, expected):
        self.expected, self.seen = set(expected), set()

    def observe(self, event):
        if event.get('event') == 'log':
            self.seen.update(re.findall(r'\bModel:\s+([\w.]+)', str(event.get('message', ''))))

    def validate(self):
        if not self.seen.intersection(self.expected):
            raise RuntimeError('Topaz 实际加载模型与所选模型不符，已停止交付，详情见任务日志')
