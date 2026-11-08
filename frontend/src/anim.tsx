// Число, которое «докручивается» к новому значению (итог во время живой оценки).
// Первое значение показывается сразу, анимируются только изменения; reduced motion — без анимации.
import { animate, useReducedMotion } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';

export function CountUp({ value, format }: { value: number | null; format: (x: number | null) => string }) {
  const [shown, setShown] = useState(value);
  const prev = useRef(value);
  const reduce = useReducedMotion();
  useEffect(() => {
    const from = prev.current;
    prev.current = value;
    if (reduce || value == null || from == null || from === value) return setShown(value);
    const c = animate(from, value, { duration: 0.5, ease: 'easeOut', onUpdate: setShown, onComplete: () => setShown(value) });
    return () => c.stop();
  }, [value, reduce]);
  return <>{format(shown)}</>;
}
