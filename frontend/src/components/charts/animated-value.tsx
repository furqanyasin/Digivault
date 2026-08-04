"use client";

import { useEffect, useRef } from "react";
import { CountUp } from "countup.js";

interface Props {
  value: number;
  suffix?: string;
  decimals?: number;
}

/** Animated numeric value. CountUp handles the tween; we only feed it the target
 *  and honour prefers-reduced-motion by jumping straight to it.
 *
 *  The server render already contains the final value, so the number is correct
 *  with JS off and there is no blank frame before the tween starts.
 */
export function AnimatedValue({ value, suffix, decimals = 0 }: Props) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.textContent = value.toFixed(decimals) + (suffix ?? "");
      return;
    }
    const counter = new CountUp(el, value, {
      duration: 1.1,
      decimalPlaces: decimals,
      suffix: suffix ?? "",
      separator: ",",
      useEasing: true,
    });
    if (counter.error) {
      el.textContent = value.toFixed(decimals) + (suffix ?? "");
      return;
    }
    counter.start();
    return () => counter.reset();
  }, [value, suffix, decimals]);

  return <span ref={ref}>{value.toFixed(decimals) + (suffix ?? "")}</span>;
}
