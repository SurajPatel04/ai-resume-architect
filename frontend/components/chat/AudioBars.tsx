"use client";

import { useEffect, useRef } from "react";

const BAR_COUNT = 5;
const MIN_HEIGHT = 3;
const MAX_HEIGHT = 24;

/**
 * Live microphone level, read straight off a WebAudio analyser.
 *
 * Heights are written to the DOM inside the animation frame rather than through state:
 * this ticks at 60fps, and re-rendering the whole composer that often makes typing
 * stutter for the sake of a decoration.
 */
export function AudioBars({ stream }: { stream: MediaStream }) {
    const barsRef = useRef<(HTMLSpanElement | null)[]>([]);

    useEffect(() => {
        const ctx = new AudioContext();
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        // Unsmoothed, every frame lands somewhere different and it reads as static
        // rather than as a voice.
        analyser.smoothingTimeConstant = 0.75;

        const source = ctx.createMediaStreamSource(stream);
        source.connect(analyser);

        // Speech lives under roughly 4kHz. Spreading the bars across the analyser's full
        // range leaves the top ones flat no matter how loudly you talk.
        const voiceBins = Math.floor(analyser.frequencyBinCount / 4);
        const perBar = Math.max(1, Math.floor(voiceBins / BAR_COUNT));
        const data = new Uint8Array(analyser.frequencyBinCount);

        let frame = requestAnimationFrame(function tick() {
            analyser.getByteFrequencyData(data);

            for (let i = 0; i < BAR_COUNT; i++) {
                const bar = barsRef.current[i];
                if (!bar) continue;

                let sum = 0;
                for (let j = i * perBar; j < (i + 1) * perBar; j++) sum += data[j];
                const level = sum / perBar / 255;

                bar.style.height = `${MIN_HEIGHT + level * (MAX_HEIGHT - MIN_HEIGHT)}px`;
            }

            frame = requestAnimationFrame(tick);
        });

        return () => {
            cancelAnimationFrame(frame);
            source.disconnect();
            ctx.close();
        };
    }, [stream]);

    return (
        <div className="flex h-6 items-center gap-[3px]" aria-hidden>
            {Array.from({ length: BAR_COUNT }, (_, i) => (
                <span
                    key={i}
                    ref={(el) => {
                        barsRef.current[i] = el;
                    }}
                    className="w-[3px] rounded-full bg-red-400 transition-none"
                    style={{ height: MIN_HEIGHT }}
                />
            ))}
        </div>
    );
}