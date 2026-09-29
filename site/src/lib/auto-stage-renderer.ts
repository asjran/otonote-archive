import { upperHiddenWindow } from './auto-stage-visibility.mjs';

export type AutoStageFrame = {
  width: number;
  height: number;
  topLeft: number;
  topWidth: number;
  bottomLeft: number;
  bottomWidth: number;
  horizonY: number;
  judgementY: number;
  boundaries: Array<{ topX: number; bottomX: number }>;
  gutter: number;
};

type NoteSlices = {
  leftUrl: string;
  centerUrl: string;
  rightUrl: string;
};

type FormalNoteSkin = {
  tap: NoteSlices;
  flick: NoteSlices;
  flickLeft: NoteSlices;
  flickRight: NoteSlices;
  slide: NoteSlices;
  slideEnd: NoteSlices;
  slideConnection?: NoteSlices;
  trace: NoteSlices;
  arrows?: Record<string, Array<{ maxWidth: number; url: string }>>;
  overlays: {
    tapDecorationUrl?: string;
    slideConnectionUrl?: string;
    flickDecorationUrl: string | null;
    flickLeftDecorationUrl: string | null;
    flickRightDecorationUrl: string | null;
    flickUpArrowUrl: string | null;
    flickLeftArrowUrl: string | null;
    flickRightArrowUrl: string | null;
    slideDecorationUrl: string | null;
  };
};

type ProjectedMarker = {
  id: string;
  kind: "tap" | "flick" | "long-node" | "long-flick" | "trace";
  direction?: string;
  isEnd?: boolean;
  nodeIndex?: number;
  size?: number;
  slopeLeft?: number;
  slopeRight?: number;
  x: number;
  y: number;
  width: number;
  centerX: number;
  depth: number;
};

type ProjectedLongPath = {
  id: string;
  kind: "long" | "guide";
  points: Array<{ x: number; y: number; width: number; centerX: number }>;
};

type AutoCue = {
  id: string;
  kind: "skill" | "fever-start" | "fever-end" | "call";
  time: number;
  label?: string;
  progress?: number;
};

export type AutoStageTheme = {
  palette: {
    top: string;
    middle: string;
    bottom: string;
    track: string;
    lane: string;
  };
  backgroundUrl: string | null;
  judgementUrl?: string | null;
  laneSkin: {
    baseUrl: string;
    tapAreaUrl: string;
    outsideLineUrl: string;
  } | null;
  noteSkin: FormalNoteSkin | null;
  effectTextures: {
    tapLineUrl: string | null;
    tapPillarUrl: string | null;
    particleStarUrl: string | null;
  } | null;
};

type RenderProfile = {
  mode: string;
  effects: boolean;
  laneGuides: boolean;
};

export type AutoStageRenderInput = {
  context: CanvasRenderingContext2D;
  frame: AutoStageFrame;
  profile: RenderProfile;
  stageTheme: AutoStageTheme;
  gameSettings: Record<string, number>;
  scene: {
    longPaths: ProjectedLongPath[];
    markers: ProjectedMarker[];
    hitEffects: ProjectedMarker[];
    activeCue: AutoCue | null;
    combo: number;
    time?: number;
    heldNotes?: Array<{ centerX: number; y: number; width: number }>;
    judgementProgress?: number | null;
    activeGekisou?: { index: number; label: string; type: string; progress: number } | null;
  };
};

type RendererOptions = {
  createNoteLayer?: () => HTMLCanvasElement;
  images: Map<string, HTMLImageElement>;
  comboSkin: {
    capability: string;
    digitUrls: Array<string | null>;
    labelUrl: string | null;
  };
  onSkinStateChange: (value: string) => void;
  labels: {
    realBackground: string;
    realLane: string;
    realNotes: string;
    formalArrows: string;
    staticEffects: string;
    cssStage: string;
  };
};

export function createAutoStageRenderer(options: RendererOptions) {
  const { images, comboSkin, onSkinStateChange, labels } = options;
  let noteLayer: HTMLCanvasElement | undefined;
  const image = (url: string | null | undefined) => {
    const candidate = url ? images.get(url) : null;
    return candidate?.complete && candidate.naturalWidth ? candidate : null;
  };

  const drawHitEffect = (
    context: CanvasRenderingContext2D,
    marker: ProjectedMarker,
    profile: RenderProfile,
    theme: AutoStageTheme
  ) => {
    if (
      profile.mode !== "full" ||
      !profile.effects ||
      !theme.effectTextures ||
      marker.depth < -0.04 ||
      marker.depth > 0.08
    ) return;
    const progress = Math.min(1, Math.max(0, -marker.depth / 0.04));
    const intensity = (1 - progress) ** 2;
    const { tapPillarUrl, particleStarUrl } =
      theme.effectTextures;
    context.save();
    context.globalAlpha = intensity * 0.9;
    context.globalCompositeOperation = "lighter";
    // The source tap-line texture is an outline intended for a game material;
    // drawing it as a flat sprite produces an empty rectangle.
    const radius = Math.max(20, marker.width * (0.55 + progress * 0.5));
    context.save();
    context.translate(marker.centerX, marker.y);
    context.scale(radius, 6 + progress * 4);
    const glow = context.createRadialGradient(0, 0, 0, 0, 0, 1);
    glow.addColorStop(0, 'rgba(230,250,255,0.9)');
    glow.addColorStop(0.35, 'rgba(120,225,255,0.4)');
    glow.addColorStop(1, 'rgba(100,205,255,0)');
    context.fillStyle = glow;
    context.beginPath();
    context.arc(0, 0, 1, 0, Math.PI * 2);
    context.fill();
    context.restore();
    const pillar = image(tapPillarUrl);
    if (pillar) {
      const height = marker.width / Math.max(1, marker.size ?? 4) * (1.5 + intensity * 2);
      const width = Math.max(16, marker.width * 0.34);
      context.drawImage(
        pillar,
        marker.centerX - width / 2,
        marker.y - height,
        width,
        height
      );
    }
    const star = image(particleStarUrl);
    if (star) {
      const size = marker.width / Math.max(1, marker.size ?? 4) * (0.55 + progress * 0.65);
      context.drawImage(
        star,
        marker.centerX - size / 2,
        marker.y - size * 0.78 - progress * 36,
        size,
        size
      );
    }
    context.restore();
  };

  const drawSlicedNote = (
    context: CanvasRenderingContext2D,
    marker: ProjectedMarker,
    skin: FormalNoteSkin | null,
    height: number
  ) => {
    if (!skin) return false;
    const family =
      marker.kind === "tap"
        ? "tap"
        : marker.kind === "trace"
          ? "trace"
        : marker.kind === "long-node"
          ? (marker.isEnd ? "slideEnd" : marker.nodeIndex ? "slideConnection" : "slide")
          : marker.direction === "left"
            ? "flickLeft"
            : marker.direction === "right"
              ? "flickRight"
              : "flick";
    const slices = skin[family];
    const left = image(slices?.leftUrl);
    const center = image(slices?.centerUrl);
    const right = image(slices?.rightUrl);
    if (!left || !center || !right) return false;
    const naturalCapWidth =
      (height * left.naturalWidth) / left.naturalHeight;
    const capWidth = Math.min(
      marker.width * 0.28,
      naturalCapWidth
    );
    const centerWidth = Math.max(1, marker.width - capWidth * 2);
    const y = marker.y - height / 2;
    const leftShift = (marker.slopeLeft ?? 0) * height / 2;
    const rightShift = (marker.slopeRight ?? 0) * height / 2;
    context.save();
    context.transform(1, 0, marker.slopeLeft ?? 0, 1, marker.x - leftShift, y);
    context.drawImage(left, 0, 0, capWidth, height);
    context.restore();
    context.save();
    const centerX = marker.x + capWidth;
    const centerRight = centerX + centerWidth;
    context.beginPath();
    context.moveTo(centerX - leftShift, y);
    context.lineTo(centerRight - rightShift, y);
    context.lineTo(centerRight + rightShift, y + height);
    context.lineTo(centerX + leftShift, y + height);
    context.closePath();
    context.clip();
    const bleed = Math.max(Math.abs(leftShift), Math.abs(rightShift));
    context.drawImage(
      center,
      centerX - bleed,
      y,
      centerWidth + bleed * 2,
      height
    );
    context.restore();
    context.save();
    context.transform(1, 0, marker.slopeRight ?? 0, 1, centerRight - rightShift, y);
    context.drawImage(
      right,
      0,
      0,
      capWidth,
      height
    );
    context.restore();
    return true;
  };

  const drawMarker = (
    context: CanvasRenderingContext2D,
    marker: ProjectedMarker,
    profile: RenderProfile,
    theme: AutoStageTheme
  ) => {
    const skin = theme.noteSkin;
    const overlays = skin?.overlays;
    const connection = marker.kind === 'long-node' && marker.nodeIndex && !marker.isEnd;
    const familyHeight = marker.kind === 'trace' ? 59 / 82 : connection ? 43 / 82 : 1;
    const height = marker.width / Math.max(1, marker.size ?? 4) * 0.98 * familyHeight;
    const decorationUrl = connection ? overlays?.slideConnectionUrl : marker.kind.includes("flick")
      ? marker.direction === "left"
        ? overlays?.flickLeftDecorationUrl
        : marker.direction === "right"
          ? overlays?.flickRightDecorationUrl
          : overlays?.flickDecorationUrl
      : marker.kind === "long-node"
        ? overlays?.slideDecorationUrl
        : marker.kind === 'tap' ? overlays?.tapDecorationUrl : null;
    const decoration = image(decorationUrl);
    if (!drawSlicedNote(context, marker, skin, height)) {
      context.beginPath();
      context.roundRect(
        marker.x,
        marker.y - height / 2,
        marker.width,
        height,
        Math.min(8, height / 2)
      );
      context.fillStyle = marker.kind.includes("flick")
        ? "#ffca5c"
        : "#66e4ff";
      context.shadowColor = context.fillStyle;
      context.shadowBlur = profile.effects ? 12 : 0;
      context.fill();
      context.shadowBlur = 0;
      context.strokeStyle = "rgba(255, 255, 255, 0.9)";
      context.lineWidth = 1.5;
      context.stroke();
    }
    if (decoration) {
      const size = height * (connection ? 1.5 : 0.34);
      context.drawImage(decoration, marker.centerX - size / 2, marker.y - size / 2, size, size);
    }
    if (!marker.kind.includes("flick")) return;
    const arrowFamily = marker.direction === 'left' ? 'left' : marker.direction === 'right' ? 'right' : 'up';
    const sizedArrow = skin?.arrows?.[arrowFamily]?.find(asset => (marker.size ?? 4) <= asset.maxWidth);
    const arrowUrl = sizedArrow?.url ?? (
      marker.direction === "left"
        ? overlays?.flickLeftArrowUrl
        : marker.direction === "right"
          ? overlays?.flickRightArrowUrl
          : overlays?.flickUpArrowUrl);
    const arrow = image(arrowUrl);
    if (arrow) {
      const arrowHeight = height * (arrowFamily === 'up' ? 1.9 : 1.65);
      const width = Math.min(marker.width * 0.88, arrowHeight * arrow.naturalWidth / arrow.naturalHeight);
      const renderedHeight = width * arrow.naturalHeight / arrow.naturalWidth;
      const y = marker.y - height * 0.48 - renderedHeight;
      context.save();
      context.globalAlpha = 0.96;
      if (marker.direction === "left") {
        context.translate(marker.centerX, 0);
        context.scale(-1, 1);
        context.drawImage(arrow, -width / 2, y, width, renderedHeight);
      } else {
        context.drawImage(
          arrow,
          marker.centerX - width / 2,
          y,
          width,
          renderedHeight
        );
      }
      context.restore();
      return;
    }
    const direction =
      marker.direction === "left" ? -1 : marker.direction === "right" ? 1 : 0;
    context.beginPath();
    context.moveTo(
      marker.centerX + direction * 8,
      marker.y - height - 9
    );
    context.lineTo(marker.centerX - 7, marker.y - height + 1);
    context.lineTo(marker.centerX + 7, marker.y - height + 1);
    context.closePath();
    context.fillStyle = "#fff5cf";
    context.fill();
  };

  const drawPath = (
    context: CanvasRenderingContext2D,
    path: ProjectedLongPath,
    profile: RenderProfile,
    settings: Record<string, number>
  ) => {
    if (path.points.length < 2) return;
    context.save();
    context.globalAlpha =
      settings[path.kind === "guide" ? "guideOpacity" : "slideOpacity"] / 100;
    context.beginPath();
    const inset = path.kind === 'long' ? 0.05 : 0;
    path.points.forEach((point, index) => {
      if (index === 0) context.moveTo(point.x + point.width * inset, point.y);
      else context.lineTo(point.x + point.width * inset, point.y);
    });
    [...path.points].reverse().forEach((point) => {
      context.lineTo(point.x + point.width * (1 - inset), point.y);
    });
    context.closePath();
    if (path.kind === "guide") {
      const gradient = context.createLinearGradient(
        0,
        path.points[0].y,
        0,
        path.points.at(-1)?.y ?? 0
      );
      gradient.addColorStop(0, "rgba(191, 125, 255, 0.56)");
      gradient.addColorStop(1, "rgba(100, 183, 255, 0.24)");
      context.fillStyle = gradient;
      context.strokeStyle = "rgba(225, 198, 255, 0.62)";
      context.lineWidth = 1.25;
    } else if (profile.mode === "minimal") {
      context.fillStyle = "rgba(88, 228, 255, 0.54)";
      context.strokeStyle = "rgba(167, 244, 255, 0.76)";
      context.lineWidth = 1.5;
    } else {
      const gradient = context.createLinearGradient(
        0,
        path.points[0].y,
        0,
        path.points.at(-1)?.y ?? 0
      );
      gradient.addColorStop(0, "rgba(78, 105, 255, 0.78)");
      gradient.addColorStop(0.55, "rgba(80, 126, 221, 0.78)");
      gradient.addColorStop(1, "rgba(77, 137, 219, 0.9)");
      context.fillStyle = gradient;
      context.strokeStyle = "rgba(120, 155, 255, 0.22)";
      context.lineWidth = 0.75;
    }
    context.fill();
    context.stroke();
    context.restore();
  };

  const drawCue = (
    context: CanvasRenderingContext2D,
    cue: AutoCue,
    frame: AutoStageFrame,
    profile: RenderProfile
  ) => {
    const labels: Record<AutoCue["kind"], string> = {
      skill: "SKILL ACTIVE",
      "fever-start": "GEKISOU START",
      "fever-end": "GEKISOU END",
      call: "RHYTHM CALL"
    };
    const width = Math.min(240, frame.width * 0.5);
    const x = (frame.width - width) / 2;
    const y = frame.width < 600 ? 62 : 18;
    context.save();
    context.globalAlpha = Math.min(1, (1 - (cue.progress ?? 0)) * 4);
    context.beginPath();
    context.roundRect(x, y, width, 32, 16);
    context.fillStyle = cue.kind.startsWith("fever")
      ? "rgba(255, 92, 171, 0.88)"
      : "rgba(90, 112, 255, 0.88)";
    context.shadowColor = context.fillStyle;
    context.shadowBlur = profile.effects ? 18 : 0;
    context.fill();
    context.shadowBlur = 0;
    context.fillStyle = "#fff";
    context.font = "800 13px system-ui, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(cue.label ?? labels[cue.kind], frame.width / 2, y + 16);
    context.textAlign = "start";
    context.textBaseline = "alphabetic";
    context.restore();
  };

  const drawCombo = (
    context: CanvasRenderingContext2D,
    frame: AutoStageFrame,
    combo: number
  ) => {
    if (combo <= 0) return;
    const digits = String(combo).split("");
    const height = Math.max(28, Math.min(58, frame.width * 0.064));
    const width = height * (102 / 139);
    const gap = -width * 0.12;
    const total = digits.length * width + Math.max(0, digits.length - 1) * gap;
    const centerX = frame.width - frame.gutter - Math.max(52, total / 2);
    const startX = centerX - total / 2;
    const y = frame.width < 600 ? 18 : frame.height * 0.18;
    const ready =
      comboSkin.capability === "available" &&
      digits.every((digit) => image(comboSkin.digitUrls[Number(digit)]));
    context.save();
    if (ready) {
      digits.forEach((digit, index) => {
        const digitImage = image(comboSkin.digitUrls[Number(digit)]);
        if (digitImage) {
          context.drawImage(
            digitImage,
            startX + index * (width + gap),
            y,
            width,
            height
          );
        }
      });
      const label = image(comboSkin.labelUrl);
      if (label) {
        const labelWidth = Math.min(92, frame.width * 0.22);
        context.drawImage(
          label,
          centerX - labelWidth / 2,
          y + height - 4,
          labelWidth,
          labelWidth * (64 / 185)
        );
      }
    } else {
      context.textAlign = "center";
      context.fillStyle = "#fff5d2";
      context.shadowColor = "#f9bd4a";
      context.shadowBlur = 0;
      context.font =
        `800 ${Math.round(height * 0.76)}px ` +
        "system-ui, sans-serif";
      context.fillText(String(combo), centerX, y + height * 0.72);
      context.shadowBlur = 0;
      context.fillStyle = "rgba(255,255,255,.9)";
      context.font = `700 ${Math.round(height * 0.2)}px sans-serif`;
      context.fillText("COMBO", centerX, y + height);
    }
    context.restore();
  };

  const drawStage = (
    context: CanvasRenderingContext2D,
    frame: AutoStageFrame,
    profile: RenderProfile,
    theme: AutoStageTheme,
    settings: Record<string, number>
  ) => {
    const palette = theme.palette;
    if (profile.mode === "minimal") context.fillStyle = palette.bottom;
    else {
      const gradient = context.createLinearGradient(0, 0, 0, frame.height);
      gradient.addColorStop(0, palette.top);
      gradient.addColorStop(0.55, palette.middle);
      gradient.addColorStop(1, palette.bottom);
      context.fillStyle = gradient;
    }
    context.fillRect(0, 0, frame.width, frame.height);
    const background = image(theme.backgroundUrl);
    if (background) {
      const height = Math.max(frame.height * 0.65, frame.width * background.naturalHeight / background.naturalWidth);
      const width = height * background.naturalWidth / background.naturalHeight;
      context.save();
      context.globalAlpha = settings.backgroundBrightness / 100;
      context.drawImage(
        background,
        (frame.width - width) / 2,
        0,
        width,
        height
      );
      context.fillStyle = "rgba(4, 8, 24, 0.18)";
      context.fillRect(0, 0, frame.width, frame.height);
      context.restore();
    }
    const laneBase = image(theme.laneSkin?.baseUrl);
    const skinReady = Boolean(laneBase);
    const noteReady = Boolean(
      theme.noteSkin &&
        [
          theme.noteSkin.tap,
          theme.noteSkin.flick,
          theme.noteSkin.flickLeft,
          theme.noteSkin.flickRight,
          theme.noteSkin.slide,
          theme.noteSkin.slideEnd,
          theme.noteSkin.trace
        ]
          .flatMap(Object.values)
          .every((url) => image(url))
    );
    const overlayReady = Boolean(
      theme.noteSkin?.overlays &&
        [
          theme.noteSkin.overlays.flickUpArrowUrl,
          theme.noteSkin.overlays.flickLeftArrowUrl,
          theme.noteSkin.overlays.flickRightArrowUrl
        ].every((url) => image(url))
    );
    const effectsReady = Boolean(
      theme.effectTextures &&
        Object.values(theme.effectTextures).some((url) => image(url))
    );
    onSkinStateChange(
      skinReady
        ? [
            background ? labels.realBackground : null,
            labels.realLane,
            noteReady ? labels.realNotes : null,
            overlayReady ? labels.formalArrows : null,
            effectsReady ? labels.staticEffects : null
          ]
            .filter(Boolean)
            .join(" + ")
        : labels.cssStage
    );
    context.beginPath();
    context.moveTo(frame.topLeft, frame.horizonY);
    context.lineTo(frame.topLeft + frame.topWidth, frame.horizonY);
    context.lineTo(
      frame.bottomLeft + frame.bottomWidth,
      frame.judgementY
    );
    context.lineTo(frame.bottomLeft, frame.judgementY);
    context.closePath();
    context.fillStyle = `rgba(${palette.track}, ${settings.laneOpacity / 100})`;
    context.fill();
    if (laneBase && theme.laneSkin) {
      context.save();
      context.globalAlpha = 0.94 * (settings.laneOpacity / 100);
      // The source has a baked trapezoid. Sample its opaque center strip and
      // clip to the same geometry as the notes, avoiding a second perspective.
      context.beginPath();
      context.moveTo(frame.topLeft, frame.horizonY);
      context.lineTo(frame.topLeft + frame.topWidth, frame.horizonY);
      context.lineTo(frame.bottomLeft + frame.bottomWidth, frame.judgementY);
      context.lineTo(frame.bottomLeft, frame.judgementY);
      context.closePath();
      context.clip();
      context.drawImage(laneBase, laneBase.naturalWidth / 2 - 8, 4, 16, laneBase.naturalHeight - 8,
        frame.bottomLeft, frame.horizonY, frame.bottomWidth, frame.judgementY - frame.horizonY);
      const outside = image(theme.laneSkin.outsideLineUrl);
      if (outside) {
        const width = Math.max(5, frame.bottomWidth / 120);
        const height = Math.min(32, frame.height * 0.06);
        context.drawImage(
          outside,
          frame.bottomLeft - width,
          frame.judgementY - height,
          width,
          height
        );
        context.drawImage(
          outside,
          frame.bottomLeft + frame.bottomWidth,
          frame.judgementY - height,
          width,
          height
        );
      }
      context.restore();
    }
    for (const [index, boundary] of frame.boundaries.entries()) {
      const outer = index === 0 || index === frame.boundaries.length - 1;
      if (!outer && (!profile.laneGuides || index % 2 !== 0)) continue;
      context.beginPath();
      context.moveTo(boundary.topX, frame.horizonY);
      context.lineTo(boundary.bottomX, frame.judgementY);
      const opacity = settings.guidelineOpacity / 100;
      context.strokeStyle = outer
        ? `rgba(${palette.lane}, ${0.72 * opacity})`
        : `rgba(${palette.lane}, ${0.36 * opacity})`;
      context.lineWidth = outer ? 2 : 1;
      context.stroke();
    }
    context.beginPath();
    context.moveTo(frame.bottomLeft, frame.judgementY);
    context.lineTo(
      frame.bottomLeft + frame.bottomWidth,
      frame.judgementY
    );
    context.strokeStyle = "#f5f7ff";
    context.shadowColor = `rgb(${palette.lane})`;
    context.shadowBlur = profile.effects ? 16 : 0;
    context.lineWidth = 4;
    context.stroke();
    context.shadowBlur = 0;
  };

  const drawFeedback = (context: CanvasRenderingContext2D, frame: AutoStageFrame, theme: AutoStageTheme,
    scene: AutoStageRenderInput["scene"], profile: RenderProfile) => {
    context.save();
    const active = scene.activeGekisou;
    if (active) {
      const color = active.type === 'luck' ? '#6ef2b9' : active.type === 'just' ? '#83caff' : '#ed8bd5';
      context.fillStyle = '#071120dd';
      context.beginPath();
      context.roundRect(16, 16, 140, 38, 8);
      context.fill();
      context.fillStyle = color;
      context.fillRect(20, 50, 132 * active.progress, 2);
      context.font = '700 12px system-ui, sans-serif';
      context.fillText(`${active.index} · ${active.label}`, 28, 39);
      context.strokeStyle = color;
      context.lineWidth = profile.effects ? 4 : 2;
      context.shadowColor = color;
      context.shadowBlur = profile.effects ? 14 : 0;
      for (const boundary of [frame.boundaries[0], frame.boundaries.at(-1)!]) {
        context.beginPath(); context.moveTo(boundary.topX, frame.horizonY); context.lineTo(boundary.bottomX, frame.judgementY); context.stroke();
      }
      context.shadowBlur = 0;
    }
    if (profile.effects) {
      context.globalCompositeOperation = 'lighter';
      for (const held of scene.heldNotes ?? []) {
        const pulse = 0.65 + Math.sin((scene.time ?? 0) * 18) * 0.15;
        const gradient = context.createRadialGradient(held.centerX, held.y, 0, held.centerX, held.y, Math.max(12, held.width));
        gradient.addColorStop(0, `rgba(125,240,255,${pulse})`); gradient.addColorStop(1, 'rgba(125,240,255,0)');
        context.fillStyle = gradient;
        context.fillRect(held.centerX - held.width, held.y - 34, held.width * 2, 48);
      }
      context.globalCompositeOperation = 'source-over';
    }
    if (scene.judgementProgress != null) {
      const judgement = image(theme.judgementUrl);
      const width = Math.min(170, frame.width * 0.34);
      const height = judgement ? width * judgement.naturalHeight / judgement.naturalWidth : 30;
      const progress = scene.judgementProgress;
      context.globalAlpha = Math.min(1, (1 - progress) * 3);
      const y = frame.judgementY - height - 34 - (profile.effects ? progress * 6 : 0);
      if (judgement) context.drawImage(judgement, frame.width / 2 - width / 2, y, width, height);
      else {
        context.fillStyle = '#fff3b6'; context.font = '800 20px system-ui, sans-serif'; context.textAlign = 'center';
        context.fillText('PERFECT', frame.width / 2, y + 20);
      }
    }
    context.restore();
  };

  return {
    render(input: AutoStageRenderInput) {
      const { context, frame, profile, stageTheme, gameSettings, scene } =
        input;
      drawStage(context, frame, profile, stageTheme, gameSettings);
      const drawNotes = (target: CanvasRenderingContext2D) => {
        scene.longPaths.forEach(path => drawPath(target, path, profile, gameSettings));
        scene.markers.forEach(marker => drawMarker(target, marker, profile, stageTheme));
      };
      const hidden = upperHiddenWindow(frame, gameSettings.hiddenHeight, gameSettings.hiddenFade);
      if (hidden) {
        // Mask only a separate note layer. The stage, judgement line and HUD
        // must remain visible, and the timeline must never be filtered.
        noteLayer ??= options.createNoteLayer?.() ?? document.createElement('canvas');
        if (noteLayer.width !== context.canvas.width) noteLayer.width = context.canvas.width;
        if (noteLayer.height !== context.canvas.height) noteLayer.height = context.canvas.height;
        const layer = noteLayer.getContext('2d');
        if (layer) {
          layer.setTransform(1, 0, 0, 1, 0, 0);
          layer.clearRect(0, 0, noteLayer.width, noteLayer.height);
          layer.setTransform(context.getTransform());
          drawNotes(layer);
          if (hidden.end === hidden.start) {
            layer.clearRect(0, 0, frame.width, hidden.start);
          } else {
            layer.save();
            layer.globalCompositeOperation = 'destination-in';
            const mask = layer.createLinearGradient(0, hidden.start, 0, hidden.end);
            mask.addColorStop(0, 'rgba(0,0,0,0)');
            mask.addColorStop(1, 'rgba(0,0,0,1)');
            layer.fillStyle = mask;
            layer.fillRect(0, 0, frame.width, frame.height);
            layer.restore();
          }
          context.drawImage(noteLayer, 0, 0, frame.width, frame.height);
        } else drawNotes(context);
      } else drawNotes(context);
      scene.hitEffects.forEach((marker) =>
        drawHitEffect(context, marker, profile, stageTheme)
      );
      drawFeedback(context, frame, stageTheme, scene, profile);
      if (scene.activeCue) {
        drawCue(context, scene.activeCue, frame, profile);
      }
      drawCombo(context, frame, scene.combo);
    }
  };
}
