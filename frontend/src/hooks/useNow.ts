import { useEffect, useState } from 'react';

export function useNow(every = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => { if (!document.hidden) setNow(Date.now()); }, every);
    return () => window.clearInterval(timer);
  }, [every]);
  return now;
}
