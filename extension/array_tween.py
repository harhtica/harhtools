"""Small, deterministic motion layer for the Array ghost preview.

Only rigid group transforms are animated. Scene objects and source geometry
are never touched; callers draw the sampled matrices with their cached mesh.
"""
from dataclasses import dataclass
import time

from mathutils import Matrix


_UNSET = object()


def _clock(now):
    return time.monotonic() if now is None else float(now)


def _near(a, b):
    return all(abs(x - y) <= 1e-7 * max(1, abs(x), abs(y))
               for ra, rb in zip(a, b) for x, y in zip(ra, rb))


def _unit(value):
    return min(1.0, max(0.0, value))


def _ease(value, style):
    t = _unit(value)
    if style == 'BACK':
        # Gentler than the usual 1.70158 Back coefficient: a slight settle,
        # not a large bounce when a long row or radius changes.
        shifted = t - 1.0
        return 1.0 + 1.9 * shifted ** 3 + .9 * shifted ** 2
    return 1.0 - (1.0 - t) ** 2


def _rigid_mix(a, b, amount):
    position = a.translation.lerp(b.translation, amount)
    qa, qb = a.to_quaternion(), b.to_quaternion()
    qa.normalize()
    qb.normalize()
    if qa.dot(qb) < 0:
        qb.negate()
    # Translation gets the soft Back settle. Rotation uses a bounded shortest
    # arc so even a 180-degree target remains rigid and cannot flip or shear.
    rotation = qa.slerp(qb, _unit(amount))
    rotation.normalize()
    result = rotation.to_matrix().to_4x4()
    result.translation = position
    return result


@dataclass
class _Item:
    start: Matrix
    target: Matrix
    start_alpha: float
    target_alpha: float
    started: float
    duration: float
    fade_duration: float
    style: str
    present: bool

    def value(self, now):
        elapsed = max(0.0, now - self.started)
        move_t = 1.0 if self.duration <= 0 else elapsed / self.duration
        fade_t = 1.0 if self.fade_duration <= 0 else elapsed / self.fade_duration
        matrix = self.target.copy() if move_t >= 1 else _rigid_mix(self.start, self.target, _ease(move_t, self.style))
        alpha = self.start_alpha + (self.target_alpha - self.start_alpha) * _ease(fade_t, 'QUAD')
        return matrix, _unit(alpha)

    def active(self, now):
        return now < self.started + max(self.duration, self.fade_duration)


class TweenPreview:
    """Retargetable preview slots; times may be supplied for deterministic tests."""

    def __init__(self):
        self.clear()

    def clear(self):
        self._items = {}
        self._targets = ()
        self._signature = _UNSET
        self._mode = None
        self._fitted = False

    def settle(self):
        """Finish visible slots immediately and discard every retiring slot.

        Useful after an in-place source transform or geometry change: the
        refreshed mesh stays visible without animating from a stale frame.
        """
        self._items = {
            slot: _Item(item.target.copy(), item.target.copy(), 1.0, 1.0,
                        float('-inf'), 0.0, 0.0, 'QUAD', True)
            for slot, item in self._items.items() if item.present
        }

    def _sample_items(self, now):
        expired = [slot for slot, item in self._items.items()
                   if not item.present and not item.active(now)]
        for slot in expired:
            del self._items[slot]
        return {slot: item.value(now) for slot, item in self._items.items()}

    def retarget(self, transforms, signature, mode='LINEAR', fitted=False, now=None):
        """Animate toward new targets, returning False for an unchanged plan.

        ``signature`` identifies cached source geometry. Change it whenever a
        new mesh cache replaces the old one; old ghost poses are then discarded.
        """
        now = _clock(now)
        targets = tuple(matrix.copy() for matrix in transforms)
        reset = self._signature is _UNSET or signature != self._signature or mode != self._mode
        same_style = bool(fitted) == self._fitted
        if not reset and same_style and len(targets) == len(self._targets) and all(
                _near(a, b) for a, b in zip(targets, self._targets)):
            return False
        if reset:
            self._items.clear()
            self._targets = ()
        current = self._sample_items(now)
        visible_slots = [slot for slot in current if self._items[slot].present]
        if not visible_slots:
            visible_slots = [slot for slot, (_, alpha) in current.items() if alpha > 0]
        launch = current[max(visible_slots)][0] if visible_slots else Matrix.Identity(4)
        tip = targets[-1] if targets else Matrix.Identity(4)

        for slot, target in enumerate(targets):
            old = self._items.get(slot)
            if old and old.present and same_style and _near(old.target, target):
                continue
            if old:
                start, alpha = current[slot]
            else:
                start, alpha = (target.copy() if fitted else launch.copy()), 0.0
            self._items[slot] = _Item(
                start, target, alpha, 1.0, now,
                (.16 if old else 0.0) if fitted else .32,
                .16 if fitted else .256,
                'QUAD' if fitted else 'BACK', True)

        for slot in tuple(self._items):
            if slot < len(targets):
                continue
            old = self._items[slot]
            start, alpha = current[slot]
            target = start.copy() if fitted else tip.copy()
            if not old.present and same_style and (fitted or _near(old.target, target)):
                continue
            self._items[slot] = _Item(start, target, alpha, 0.0, now,
                                     0.0 if fitted else .28,
                                     .18 if fitted else .28,
                                     'QUAD', False)

        self._targets = targets
        self._signature = signature
        self._mode = mode
        self._fitted = bool(fitted)
        return True

    def sample(self, now=None):
        """Return (rigid world-group transform, bounded opacity) in slot order."""
        values = self._sample_items(_clock(now))
        return [values[slot] for slot in sorted(values)]

    def active(self, now=None):
        """True while motion or fades still need a viewport redraw."""
        now = _clock(now)
        self._sample_items(now)
        return any(item.active(now) for item in self._items.values())
