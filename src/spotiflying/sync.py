from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True)
class Timeline:
    position: float | None = None
    duration: int = 0
    playing: bool = False
    rate: float = 1.0


class Playhead:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.timeline = Timeline()
        self.anchor = clock()
        self.correction = 0.0

    def update(self, snapshot, force=False):
        old = self.position()
        current = snapshot.position
        self.correction = 0.0
        if (not force and current is not None and old is not None
                and self.timeline.playing and snapshot.playing and abs(old - current) <= 250):
            self.correction = old - current
        self.timeline = snapshot
        self.anchor = self.clock()
        return self.correction == 0 and (
            force or (old is not None and current is not None and abs(old - current) > 250)
        )

    def position(self):
        timeline = self.timeline
        if timeline.position is None:
            return None
        elapsed = max(0, self.clock() - self.anchor) if timeline.playing else 0
        position = timeline.position + elapsed * 1000 * timeline.rate
        position += self.correction * max(0, 1 - elapsed / 0.75)
        return max(0, min(position, timeline.duration)) if timeline.duration else max(0, position)
