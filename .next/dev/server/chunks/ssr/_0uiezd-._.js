module.exports = [
"[project]/styled-system/helpers.mjs [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "__objRest",
    ()=>__objRest,
    "__spreadValues",
    ()=>__spreadValues,
    "compact",
    ()=>compact,
    "createCss",
    ()=>createCss,
    "createMergeCss",
    ()=>createMergeCss,
    "filterBaseConditions",
    ()=>filterBaseConditions,
    "getPatternStyles",
    ()=>getPatternStyles,
    "getSlotCompoundVariant",
    ()=>getSlotCompoundVariant,
    "getSlotRecipes",
    ()=>getSlotRecipes,
    "hypenateProperty",
    ()=>hypenateProperty,
    "isBaseCondition",
    ()=>isBaseCondition,
    "isObject",
    ()=>isObject,
    "mapObject",
    ()=>mapObject,
    "memo",
    ()=>memo,
    "mergeProps",
    ()=>mergeProps,
    "patternFns",
    ()=>patternFns,
    "splitProps",
    ()=>splitProps,
    "toHash",
    ()=>toHash,
    "uniq",
    ()=>uniq,
    "walkObject",
    ()=>walkObject,
    "withoutSpace",
    ()=>withoutSpace
]);
// src/assert.ts
function isObject(value) {
    return typeof value === "object" && value != null && !Array.isArray(value);
}
var isObjectOrArray = (obj)=>typeof obj === "object" && obj !== null;
// src/compact.ts
function compact(value) {
    return Object.fromEntries(Object.entries(value ?? {}).filter(([_, value2])=>value2 !== void 0));
}
// src/condition.ts
var isBaseCondition = (v)=>v === "base";
function filterBaseConditions(c) {
    return c.slice().filter((v)=>!isBaseCondition(v));
}
// src/hash.ts
function toChar(code) {
    return String.fromCharCode(code + (code > 25 ? 39 : 97));
}
function toName(code) {
    let name = "";
    let x;
    for(x = Math.abs(code); x > 52; x = x / 52 | 0)name = toChar(x % 52) + name;
    return toChar(x % 52) + name;
}
function toPhash(h, x) {
    let i = x.length;
    while(i)h = h * 33 ^ x.charCodeAt(--i);
    return h;
}
function toHash(value) {
    return toName(toPhash(5381, value) >>> 0);
}
// src/important.ts
var importantRegex = /\s*!(important)?/i;
function isImportant(value) {
    return typeof value === "string" ? importantRegex.test(value) : false;
}
function withoutImportant(value) {
    return typeof value === "string" ? value.replace(importantRegex, "").trim() : value;
}
function withoutSpace(str) {
    return typeof str === "string" ? str.replaceAll(" ", "_") : str;
}
// src/memo.ts
var memo = (fn)=>{
    const cache = /* @__PURE__ */ new Map();
    const get = (...args)=>{
        const key = JSON.stringify(args);
        if (cache.has(key)) {
            return cache.get(key);
        }
        const result = fn(...args);
        cache.set(key, result);
        return result;
    };
    return get;
};
// src/merge-props.ts
var MERGE_OMIT = /* @__PURE__ */ new Set([
    "__proto__",
    "constructor",
    "prototype"
]);
function mergeProps(...sources) {
    return sources.reduce((prev, obj)=>{
        if (!obj) return prev;
        Object.keys(obj).forEach((key)=>{
            if (MERGE_OMIT.has(key)) return;
            const prevValue = prev[key];
            const value = obj[key];
            if (isObject(prevValue) && isObject(value)) {
                prev[key] = mergeProps(prevValue, value);
            } else {
                prev[key] = value;
            }
        });
        return prev;
    }, {});
}
// src/walk-object.ts
var isNotNullish = (element)=>element != null;
function walkObject(target, predicate, options = {}) {
    const { stop, getKey } = options;
    function inner(value, path = []) {
        if (isObjectOrArray(value)) {
            const result = {};
            for (const [prop, child] of Object.entries(value)){
                const key = getKey?.(prop, child) ?? prop;
                const childPath = [
                    ...path,
                    key
                ];
                if (stop?.(value, childPath)) {
                    return predicate(value, path);
                }
                const next = inner(child, childPath);
                if (isNotNullish(next)) {
                    result[key] = next;
                }
            }
            return result;
        }
        return predicate(value, path);
    }
    return inner(target);
}
function mapObject(obj, fn) {
    if (Array.isArray(obj)) return obj.map((value)=>fn(value));
    if (!isObject(obj)) return fn(obj);
    return walkObject(obj, (value)=>fn(value));
}
// src/normalize-style-object.ts
function toResponsiveObject(values, breakpoints) {
    return values.reduce((acc, current, index)=>{
        const key = breakpoints[index];
        if (current != null) {
            acc[key] = current;
        }
        return acc;
    }, {});
}
function normalizeStyleObject(styles, context, shorthand = true) {
    const { utility, conditions } = context;
    const { hasShorthand, resolveShorthand } = utility;
    return walkObject(styles, (value)=>{
        return Array.isArray(value) ? toResponsiveObject(value, conditions.breakpoints.keys) : value;
    }, {
        stop: (value)=>Array.isArray(value),
        getKey: shorthand ? (prop)=>hasShorthand ? resolveShorthand(prop) : prop : void 0
    });
}
// src/classname.ts
var fallbackCondition = {
    shift: (v)=>v,
    finalize: (v)=>v,
    breakpoints: {
        keys: []
    }
};
var sanitize = (value)=>typeof value === "string" ? value.replaceAll(/[\n\s]+/g, " ") : value;
function createCss(context) {
    const { utility, hash, conditions: conds = fallbackCondition } = context;
    const formatClassName = (str)=>[
            utility.prefix,
            str
        ].filter(Boolean).join("-");
    const hashFn = (conditions, className)=>{
        let result;
        if (hash) {
            const baseArray = [
                ...conds.finalize(conditions),
                className
            ];
            result = formatClassName(utility.toHash(baseArray, toHash));
        } else {
            const baseArray = [
                ...conds.finalize(conditions),
                formatClassName(className)
            ];
            result = baseArray.join(":");
        }
        return result;
    };
    return memo(({ base, ...styles } = {})=>{
        const styleObject = Object.assign(styles, base);
        const normalizedObject = normalizeStyleObject(styleObject, context);
        const classNames = /* @__PURE__ */ new Set();
        walkObject(normalizedObject, (value, paths)=>{
            if (value == null) return;
            const important = isImportant(value);
            const [prop, ...allConditions] = conds.shift(paths);
            const conditions = filterBaseConditions(allConditions);
            const transformed = utility.transform(prop, withoutImportant(sanitize(value)));
            let className = hashFn(conditions, transformed.className);
            if (important) className = `${className}!`;
            classNames.add(className);
        });
        return Array.from(classNames).join(" ");
    });
}
function compactStyles(...styles) {
    return styles.flat().filter((style)=>isObject(style) && Object.keys(compact(style)).length > 0);
}
function createMergeCss(context) {
    function resolve(styles) {
        const allStyles = compactStyles(...styles);
        if (allStyles.length === 1) return allStyles;
        return allStyles.map((style)=>normalizeStyleObject(style, context));
    }
    function mergeCss(...styles) {
        return mergeProps(...resolve(styles));
    }
    function assignCss(...styles) {
        return Object.assign({}, ...resolve(styles));
    }
    return {
        mergeCss: memo(mergeCss),
        assignCss
    };
}
// src/hypenate-property.ts
var wordRegex = /([A-Z])/g;
var msRegex = /^ms-/;
var hypenateProperty = memo((property)=>{
    if (property.startsWith("--")) return property;
    return property.replace(wordRegex, "-$1").replace(msRegex, "-ms-").toLowerCase();
});
// src/is-css-function.ts
var fns = [
    "min",
    "max",
    "clamp",
    "calc"
];
var fnRegExp = new RegExp(`^(${fns.join("|")})\\(.*\\)`);
var isCssFunction = (v)=>typeof v === "string" && fnRegExp.test(v);
// src/is-css-unit.ts
var lengthUnits = "cm,mm,Q,in,pc,pt,px,em,ex,ch,rem,lh,rlh,vw,vh,vmin,vmax,vb,vi,svw,svh,lvw,lvh,dvw,dvh,cqw,cqh,cqi,cqb,cqmin,cqmax,%";
var lengthUnitsPattern = `(?:${lengthUnits.split(",").join("|")})`;
var lengthRegExp = new RegExp(`^[+-]?[0-9]*.?[0-9]+(?:[eE][+-]?[0-9]+)?${lengthUnitsPattern}$`);
var isCssUnit = (v)=>typeof v === "string" && lengthRegExp.test(v);
// src/is-css-var.ts
var isCssVar = (v)=>typeof v === "string" && /^var\(--.+\)$/.test(v);
// src/pattern-fns.ts
var patternFns = {
    map: mapObject,
    isCssFunction,
    isCssVar,
    isCssUnit
};
var getPatternStyles = (pattern, styles)=>{
    if (!pattern?.defaultValues) return styles;
    const defaults = typeof pattern.defaultValues === "function" ? pattern.defaultValues(styles) : pattern.defaultValues;
    return Object.assign({}, defaults, compact(styles));
};
// src/slot.ts
var getSlotRecipes = (recipe = {})=>{
    const init = (slot)=>({
            className: [
                recipe.className,
                slot
            ].filter(Boolean).join("__"),
            base: recipe.base?.[slot] ?? {},
            variants: {},
            defaultVariants: recipe.defaultVariants ?? {},
            compoundVariants: recipe.compoundVariants ? getSlotCompoundVariant(recipe.compoundVariants, slot) : []
        });
    const slots = recipe.slots ?? [];
    const recipeParts = slots.map((slot)=>[
            slot,
            init(slot)
        ]);
    for (const [variantsKey, variantsSpec] of Object.entries(recipe.variants ?? {})){
        for (const [variantKey, variantSpec] of Object.entries(variantsSpec)){
            recipeParts.forEach(([slot, slotRecipe])=>{
                slotRecipe.variants[variantsKey] ??= {};
                slotRecipe.variants[variantsKey][variantKey] = variantSpec[slot] ?? {};
            });
        }
    }
    return Object.fromEntries(recipeParts);
};
var getSlotCompoundVariant = (compoundVariants, slotName)=>compoundVariants.filter((compoundVariant)=>compoundVariant.css[slotName]).map((compoundVariant)=>({
            ...compoundVariant,
            css: compoundVariant.css[slotName]
        }));
// src/split-props.ts
function splitProps(props, ...keys) {
    const descriptors = Object.getOwnPropertyDescriptors(props);
    const dKeys = Object.keys(descriptors);
    const split = (k)=>{
        const clone = {};
        for(let i = 0; i < k.length; i++){
            const key = k[i];
            if (descriptors[key]) {
                Object.defineProperty(clone, key, descriptors[key]);
                delete descriptors[key];
            }
        }
        return clone;
    };
    const fn = (key)=>split(Array.isArray(key) ? key : dKeys.filter(key));
    return keys.map(fn).concat(split(dKeys));
}
// src/uniq.ts
var uniq = (...items)=>{
    const set = items.reduce((acc, currItems)=>{
        if (currItems) {
            currItems.forEach((item)=>acc.add(item));
        }
        return acc;
    }, /* @__PURE__ */ new Set([]));
    return Array.from(set);
};
;
function __spreadValues(a, b) {
    return {
        ...a,
        ...b
    };
}
function __objRest(source, exclude) {
    return Object.fromEntries(Object.entries(source).filter(([key])=>!exclude.includes(key)));
}
}),
"[project]/styled-system/css/conditions.mjs [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "finalizeConditions",
    ()=>finalizeConditions,
    "isCondition",
    ()=>isCondition,
    "sortConditions",
    ()=>sortConditions
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/helpers.mjs [app-ssr] (ecmascript)");
;
const conditionsStr = "_hover,_focus,_focusWithin,_focusVisible,_disabled,_active,_visited,_target,_readOnly,_readWrite,_empty,_checked,_enabled,_expanded,_highlighted,_complete,_incomplete,_dragging,_before,_after,_firstLetter,_firstLine,_marker,_selection,_file,_backdrop,_first,_last,_only,_even,_odd,_firstOfType,_lastOfType,_onlyOfType,_peerFocus,_peerHover,_peerActive,_peerFocusWithin,_peerFocusVisible,_peerDisabled,_peerChecked,_peerInvalid,_peerExpanded,_peerPlaceholderShown,_groupFocus,_groupHover,_groupActive,_groupFocusWithin,_groupFocusVisible,_groupDisabled,_groupChecked,_groupExpanded,_groupInvalid,_indeterminate,_required,_valid,_invalid,_autofill,_inRange,_outOfRange,_placeholder,_placeholderShown,_pressed,_selected,_grabbed,_underValue,_overValue,_atValue,_default,_optional,_open,_closed,_fullscreen,_loading,_hidden,_current,_currentPage,_currentStep,_today,_unavailable,_rangeStart,_rangeEnd,_now,_topmost,_motionReduce,_motionSafe,_print,_landscape,_portrait,_dark,_light,_osDark,_osLight,_highContrast,_lessContrast,_moreContrast,_ltr,_rtl,_scrollbar,_scrollbarThumb,_scrollbarTrack,_horizontal,_vertical,_icon,_starting,_noscript,_invertedColors,sm,smOnly,smDown,md,mdOnly,mdDown,lg,lgOnly,lgDown,xl,xlOnly,xlDown,2xl,2xlOnly,2xlDown,smToMd,smToLg,smToXl,smTo2xl,mdToLg,mdToXl,mdTo2xl,lgToXl,lgTo2xl,xlTo2xl,@/xs,@/sm,@/md,@/lg,@/xl,@/2xl,@/3xl,@/4xl,@/5xl,@/6xl,@/7xl,@/8xl,base";
const conditions = new Set(conditionsStr.split(','));
const conditionRegex = /^@|&|&$/;
function isCondition(value) {
    return conditions.has(value) || conditionRegex.test(value);
}
const underscoreRegex = /^_/;
const conditionsSelectorRegex = /&|@/;
function finalizeConditions(paths) {
    return paths.map((path)=>{
        if (conditions.has(path)) {
            return path.replace(underscoreRegex, '');
        }
        if (conditionsSelectorRegex.test(path)) {
            return `[${(0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["withoutSpace"])(path.trim())}]`;
        }
        return path;
    });
}
function sortConditions(paths) {
    return paths.sort((a, b)=>{
        const aa = isCondition(a);
        const bb = isCondition(b);
        if (aa && !bb) return 1;
        if (!aa && bb) return -1;
        return 0;
    });
}
}),
"[project]/styled-system/css/css.mjs [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "assignCss",
    ()=>assignCss,
    "css",
    ()=>css,
    "mergeCss",
    ()=>mergeCss
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/helpers.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$conditions$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/conditions.mjs [app-ssr] (ecmascript)");
;
;
const utilities = "aspectRatio:asp,boxDecorationBreak:bx-db,zIndex:z,boxSizing:bx-s,objectPosition:obj-p,objectFit:obj-f,overscrollBehavior:ovs-b,overscrollBehaviorX:ovs-bx,overscrollBehaviorY:ovs-by,position:pos/1,top:top,left:left,inset:inset,insetInline:inset-x/insetX,insetBlock:inset-y/insetY,insetBlockEnd:inset-be,insetBlockStart:inset-bs,insetInlineEnd:inset-e/insetEnd/end,insetInlineStart:inset-s/insetStart/start,right:right,bottom:bottom,float:float,visibility:vis,display:d,hideFrom:hide,hideBelow:show,flexBasis:flex-b,flex:flex,flexDirection:flex-d/flexDir,flexGrow:flex-g,flexShrink:flex-sh,gridTemplateColumns:grid-tc,gridTemplateRows:grid-tr,gridColumn:grid-c,gridRow:grid-r,gridColumnStart:grid-cs,gridColumnEnd:grid-ce,gridAutoFlow:grid-af,gridAutoColumns:grid-ac,gridAutoRows:grid-ar,gap:gap,gridGap:grid-g,gridRowGap:grid-rg,gridColumnGap:grid-cg,rowGap:rg,columnGap:cg,justifyContent:jc,alignContent:ac,alignItems:ai,alignSelf:as,padding:p/1,paddingLeft:pl/1,paddingRight:pr/1,paddingTop:pt/1,paddingBottom:pb/1,paddingBlock:py/1/paddingY,paddingBlockEnd:pbe,paddingBlockStart:pbs,paddingInline:px/paddingX/1,paddingInlineEnd:pe/1/paddingEnd,paddingInlineStart:ps/1/paddingStart,marginLeft:ml/1,marginRight:mr/1,marginTop:mt/1,marginBottom:mb/1,margin:m/1,marginBlock:my/1/marginY,marginBlockEnd:mbe,marginBlockStart:mbs,marginInline:mx/1/marginX,marginInlineEnd:me/1/marginEnd,marginInlineStart:ms/1/marginStart,spaceX:sx,spaceY:sy,outlineWidth:ring-w/ringWidth,outlineColor:ring-c/ringColor,outline:ring/1,outlineOffset:ring-o/ringOffset,focusRing:focus-ring,focusVisibleRing:focus-v-ring,focusRingColor:focus-ring-c,focusRingOffset:focus-ring-o,focusRingWidth:focus-ring-w,focusRingStyle:focus-ring-s,divideX:dvd-x,divideY:dvd-y,divideColor:dvd-c,divideStyle:dvd-s,width:w/1,inlineSize:w-is,minWidth:min-w/minW,minInlineSize:min-w-is,maxWidth:max-w/maxW,maxInlineSize:max-w-is,height:h/1,blockSize:h-bs,minHeight:min-h/minH,minBlockSize:min-h-bs,maxHeight:max-h/maxH,maxBlockSize:max-b,boxSize:size,color:c,fontFamily:ff,fontSize:fs,fontSizeAdjust:fs-a,fontPalette:fp,fontKerning:fk,fontFeatureSettings:ff-s,fontWeight:fw,fontSmoothing:fsmt,fontVariant:fv,fontVariantAlternates:fv-alt,fontVariantCaps:fv-caps,fontVariationSettings:fv-s,fontVariantNumeric:fv-num,letterSpacing:ls,lineHeight:lh,textAlign:ta,textDecoration:td,textDecorationColor:td-c,textEmphasisColor:te-c,textDecorationStyle:td-s,textDecorationThickness:td-t,textUnderlineOffset:tu-o,textTransform:tt,textIndent:ti,textShadow:tsh,textShadowColor:tsh-c/textShadowColor,WebkitTextFillColor:wktf-c,textOverflow:tov,verticalAlign:va,wordBreak:wb,textWrap:tw,truncate:trunc,lineClamp:lc,listStyleType:li-t,listStylePosition:li-pos,listStyleImage:li-img,listStyle:li-s,backgroundPosition:bg-p/bgPosition,backgroundPositionX:bg-p-x/bgPositionX,backgroundPositionY:bg-p-y/bgPositionY,backgroundAttachment:bg-a/bgAttachment,backgroundClip:bg-cp/bgClip,background:bg/1,backgroundColor:bg-c/bgColor,backgroundOrigin:bg-o/bgOrigin,backgroundImage:bg-i/bgImage,backgroundRepeat:bg-r/bgRepeat,backgroundBlendMode:bg-bm/bgBlendMode,backgroundSize:bg-s/bgSize,backgroundGradient:bg-grad/bgGradient,backgroundLinear:bg-linear/bgLinear,backgroundRadial:bg-radial/bgRadial,backgroundConic:bg-conic/bgConic,textGradient:txt-grad,gradientFromPosition:grad-from-pos,gradientToPosition:grad-to-pos,gradientFrom:grad-from,gradientTo:grad-to,gradientVia:grad-via,gradientViaPosition:grad-via-pos,borderRadius:bdr/rounded,borderTopLeftRadius:bdr-tl/roundedTopLeft,borderTopRightRadius:bdr-tr/roundedTopRight,borderBottomRightRadius:bdr-br/roundedBottomRight,borderBottomLeftRadius:bdr-bl/roundedBottomLeft,borderTopRadius:bdr-t/roundedTop,borderRightRadius:bdr-r/roundedRight,borderBottomRadius:bdr-b/roundedBottom,borderLeftRadius:bdr-l/roundedLeft,borderStartStartRadius:bdr-ss/roundedStartStart,borderStartEndRadius:bdr-se/roundedStartEnd,borderStartRadius:bdr-s/roundedStart,borderEndStartRadius:bdr-es/roundedEndStart,borderEndEndRadius:bdr-ee/roundedEndEnd,borderEndRadius:bdr-e/roundedEnd,border:bd,borderWidth:bd-w,borderTopWidth:bd-t-w,borderLeftWidth:bd-l-w,borderRightWidth:bd-r-w,borderBottomWidth:bd-b-w,borderBlockStartWidth:bd-bs-w,borderBlockEndWidth:bd-be-w,borderColor:bd-c,borderInline:bd-x/borderX,borderInlineWidth:bd-x-w/borderXWidth,borderInlineColor:bd-x-c/borderXColor,borderBlock:bd-y/borderY,borderBlockWidth:bd-y-w/borderYWidth,borderBlockColor:bd-y-c/borderYColor,borderLeft:bd-l,borderLeftColor:bd-l-c,borderInlineStart:bd-s/borderStart,borderInlineStartWidth:bd-s-w/borderStartWidth,borderInlineStartColor:bd-s-c/borderStartColor,borderRight:bd-r,borderRightColor:bd-r-c,borderInlineEnd:bd-e/borderEnd,borderInlineEndWidth:bd-e-w/borderEndWidth,borderInlineEndColor:bd-e-c/borderEndColor,borderTop:bd-t,borderTopColor:bd-t-c,borderBottom:bd-b,borderBottomColor:bd-b-c,borderBlockEnd:bd-be,borderBlockEndColor:bd-be-c,borderBlockStart:bd-bs,borderBlockStartColor:bd-bs-c,opacity:op,boxShadow:bx-sh/shadow,boxShadowColor:bx-sh-c/shadowColor,mixBlendMode:mix-bm,filter:filter,brightness:brightness,contrast:contrast,grayscale:grayscale,hueRotate:hue-rotate,invert:invert,saturate:saturate,sepia:sepia,dropShadow:drop-shadow,blur:blur,backdropFilter:bkdp,backdropBlur:bkdp-blur,backdropBrightness:bkdp-brightness,backdropContrast:bkdp-contrast,backdropGrayscale:bkdp-grayscale,backdropHueRotate:bkdp-hue-rotate,backdropInvert:bkdp-invert,backdropOpacity:bkdp-opacity,backdropSaturate:bkdp-saturate,backdropSepia:bkdp-sepia,borderCollapse:bd-cl,borderSpacing:bd-sp,borderSpacingX:bd-sx,borderSpacingY:bd-sy,tableLayout:tbl,transitionTimingFunction:trs-tmf,transitionDelay:trs-dly,transitionDuration:trs-dur,transitionProperty:trs-prop,transition:trs,animation:anim,animationName:anim-n,animationTimingFunction:anim-tmf,animationDuration:anim-dur,animationDelay:anim-dly,animationPlayState:anim-ps,animationComposition:anim-comp,animationFillMode:anim-fm,animationDirection:anim-dir,animationIterationCount:anim-ic,animationRange:anim-r,animationState:anim-s,animationRangeStart:anim-rs,animationRangeEnd:anim-re,animationTimeline:anim-tl,transformOrigin:trf-o,transformBox:trf-b,transformStyle:trf-s,transform:trf,rotate:rotate,rotateX:rotate-x,rotateY:rotate-y,rotateZ:rotate-z,scale:scale,scaleX:scale-x,scaleY:scale-y,translate:translate,translateX:translate-x/x,translateY:translate-y/y,translateZ:translate-z/z,accentColor:ac-c,caretColor:ca-c,scrollBehavior:scr-bhv,scrollbar:scr-bar,scrollbarColor:scr-bar-c,scrollbarGutter:scr-bar-g,scrollbarWidth:scr-bar-w,scrollMargin:scr-m,scrollMarginLeft:scr-ml,scrollMarginRight:scr-mr,scrollMarginTop:scr-mt,scrollMarginBottom:scr-mb,scrollMarginBlock:scr-my/scrollMarginY,scrollMarginBlockEnd:scr-mbe,scrollMarginBlockStart:scr-mbt,scrollMarginInline:scr-mx/scrollMarginX,scrollMarginInlineEnd:scr-me,scrollMarginInlineStart:scr-ms,scrollPadding:scr-p,scrollPaddingBlock:scr-py/scrollPaddingY,scrollPaddingBlockStart:scr-pbs,scrollPaddingBlockEnd:scr-pbe,scrollPaddingInline:scr-px/scrollPaddingX,scrollPaddingInlineEnd:scr-pe,scrollPaddingInlineStart:scr-ps,scrollPaddingLeft:scr-pl,scrollPaddingRight:scr-pr,scrollPaddingTop:scr-pt,scrollPaddingBottom:scr-pb,scrollSnapAlign:scr-sa,scrollSnapStop:scrs-s,scrollSnapType:scrs-t,scrollSnapStrictness:scrs-strt,scrollSnapMargin:scrs-m,scrollSnapMarginTop:scrs-mt,scrollSnapMarginBottom:scrs-mb,scrollSnapMarginLeft:scrs-ml,scrollSnapMarginRight:scrs-mr,scrollSnapCoordinate:scrs-c,scrollSnapDestination:scrs-d,scrollSnapPointsX:scrs-px,scrollSnapPointsY:scrs-py,scrollSnapTypeX:scrs-tx,scrollSnapTypeY:scrs-ty,scrollTimeline:scrtl,scrollTimelineAxis:scrtl-a,scrollTimelineName:scrtl-n,touchAction:tch-a,userSelect:us,overflow:ov,overflowWrap:ov-wrap,overflowX:ov-x,overflowY:ov-y,overflowAnchor:ov-a,overflowBlock:ov-b,overflowInline:ov-i,overflowClipBox:ovcp-bx,overflowClipMargin:ovcp-m,overscrollBehaviorBlock:ovs-bb,overscrollBehaviorInline:ovs-bi,fill:fill,stroke:stk,strokeWidth:stk-w,strokeDasharray:stk-dsh,strokeDashoffset:stk-do,strokeLinecap:stk-lc,strokeLinejoin:stk-lj,strokeMiterlimit:stk-ml,strokeOpacity:stk-op,srOnly:sr,debug:debug,appearance:ap,backfaceVisibility:bfv,clipPath:cp-path,hyphens:hy,mask:msk,maskImage:msk-i,maskSize:msk-s,textSizeAdjust:txt-adj,container:cq,containerName:cq-n,containerType:cq-t,cursor:cursor,textStyle:textStyle";
const classNameByProp = new Map();
const shorthands = new Map();
utilities.split(',').forEach((utility)=>{
    const [prop, meta] = utility.split(':');
    const [className, ...shorthandList] = meta.split('/');
    classNameByProp.set(prop, className);
    if (shorthandList.length) {
        shorthandList.forEach((shorthand)=>{
            shorthands.set(shorthand === '1' ? className : shorthand, prop);
        });
    }
});
const resolveShorthand = (prop)=>shorthands.get(prop) || prop;
const context = {
    conditions: {
        shift: __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$conditions$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["sortConditions"],
        finalize: __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$conditions$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["finalizeConditions"],
        breakpoints: {
            keys: [
                "base",
                "sm",
                "md",
                "lg",
                "xl",
                "2xl"
            ]
        }
    },
    utility: {
        transform: (prop, value)=>{
            const key = resolveShorthand(prop);
            const propKey = classNameByProp.get(key) || (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["hypenateProperty"])(key);
            return {
                className: `${propKey}_${(0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["withoutSpace"])(value)}`
            };
        },
        hasShorthand: true,
        toHash: (path, hashFn)=>hashFn(path.join(":")),
        resolveShorthand: resolveShorthand
    }
};
const cssFn = (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["createCss"])(context);
const css = (...styles)=>cssFn(mergeCss(...styles));
css.raw = (...styles)=>mergeCss(...styles);
const { mergeCss, assignCss } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["createMergeCss"])(context);
}),
"[project]/styled-system/css/cva.mjs [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "assertCompoundVariant",
    ()=>assertCompoundVariant,
    "cva",
    ()=>cva,
    "getCompoundVariantCss",
    ()=>getCompoundVariantCss
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/helpers.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/css.mjs [app-ssr] (ecmascript)");
;
;
const defaults = (conf)=>({
        base: {},
        variants: {},
        defaultVariants: {},
        compoundVariants: [],
        ...conf
    });
function cva(config) {
    const { base, variants, defaultVariants, compoundVariants } = defaults(config);
    const getVariantProps = (variants)=>({
            ...defaultVariants,
            ...(0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["compact"])(variants)
        });
    function resolve(props = {}) {
        const computedVariants = getVariantProps(props);
        let variantCss = {
            ...base
        };
        for (const [key, value] of Object.entries(computedVariants)){
            if (variants[key]?.[value]) {
                variantCss = (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["mergeCss"])(variantCss, variants[key][value]);
            }
        }
        const compoundVariantCss = getCompoundVariantCss(compoundVariants, computedVariants);
        return (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["mergeCss"])(variantCss, compoundVariantCss);
    }
    function merge(__cva) {
        const override = defaults(__cva.config);
        const variantKeys = (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["uniq"])(__cva.variantKeys, Object.keys(variants));
        return cva({
            base: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["mergeCss"])(base, override.base),
            variants: Object.fromEntries(variantKeys.map((key)=>[
                    key,
                    (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["mergeCss"])(variants[key], override.variants[key])
                ])),
            defaultVariants: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["mergeProps"])(defaultVariants, override.defaultVariants),
            compoundVariants: [
                ...compoundVariants,
                ...override.compoundVariants
            ]
        });
    }
    function cvaFn(props) {
        return (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])(resolve(props));
    }
    const variantKeys = Object.keys(variants);
    function splitVariantProps(props) {
        return (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["splitProps"])(props, variantKeys);
    }
    const variantMap = Object.fromEntries(Object.entries(variants).map(([key, value])=>[
            key,
            Object.keys(value)
        ]));
    return Object.assign((0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["memo"])(cvaFn), {
        __cva__: true,
        variantMap,
        variantKeys,
        raw: resolve,
        config,
        merge,
        splitVariantProps,
        getVariantProps
    });
}
function getCompoundVariantCss(compoundVariants, variantMap) {
    let result = {};
    compoundVariants.forEach((compoundVariant)=>{
        const isMatching = Object.entries(compoundVariant).every(([key, value])=>{
            if (key === 'css') return true;
            const values = Array.isArray(value) ? value : [
                value
            ];
            return values.some((value)=>variantMap[key] === value);
        });
        if (isMatching) {
            result = (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["mergeCss"])(result, compoundVariant.css);
        }
    });
    return result;
}
function assertCompoundVariant(name, compoundVariants, variants, prop) {
    if (compoundVariants.length > 0 && typeof variants?.[prop] === 'object') {
        throw new Error(`[recipe:${name}:${prop}] Conditions are not supported when using compound variants.`);
    }
}
}),
"[project]/styled-system/css/cx.mjs [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "cx",
    ()=>cx
]);
function cx() {
    let str = '', i = 0, arg;
    for(; i < arguments.length;){
        if ((arg = arguments[i++]) && typeof arg === 'string') {
            str && (str += ' ');
            str += arg;
        }
    }
    return str;
}
;
}),
"[project]/styled-system/css/sva.mjs [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "sva",
    ()=>sva
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/helpers.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$cva$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/cva.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$cx$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/cx.mjs [app-ssr] (ecmascript)");
;
;
;
function sva(config) {
    const slots = Object.entries((0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["getSlotRecipes"])(config)).map(([slot, slotCva])=>[
            slot,
            (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$cva$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["cva"])(slotCva)
        ]);
    const defaultVariants = config.defaultVariants ?? {};
    const classNameMap = slots.reduce((acc, [slot, cvaFn])=>{
        if (config.className) acc[slot] = cvaFn.config.className;
        return acc;
    }, {});
    function svaFn(props) {
        const result = slots.map(([slot, cvaFn])=>[
                slot,
                (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$cx$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["cx"])(cvaFn(props), classNameMap[slot])
            ]);
        return Object.fromEntries(result);
    }
    function raw(props) {
        const result = slots.map(([slot, cvaFn])=>[
                slot,
                cvaFn.raw(props)
            ]);
        return Object.fromEntries(result);
    }
    const variants = config.variants ?? {};
    const variantKeys = Object.keys(variants);
    function splitVariantProps(props) {
        return (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["splitProps"])(props, variantKeys);
    }
    const getVariantProps = (variants)=>({
            ...defaultVariants,
            ...(0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["compact"])(variants)
        });
    const variantMap = Object.fromEntries(Object.entries(variants).map(([key, value])=>[
            key,
            Object.keys(value)
        ]));
    return Object.assign((0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["memo"])(svaFn), {
        __cva__: false,
        raw,
        config,
        variantMap,
        variantKeys,
        classNameMap,
        splitVariantProps,
        getVariantProps
    });
}
}),
"[project]/styled-system/css/index.mjs [app-ssr] (ecmascript) <locals>", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([]);
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/css.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$cva$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/cva.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$sva$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/sva.mjs [app-ssr] (ecmascript)");
;
;
;
;
}),
"[project]/src/components/layout/DashboardShell.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "DashboardShell",
    ()=>DashboardShell
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$locals$3e$__ = __turbopack_context__.i("[project]/styled-system/css/index.mjs [app-ssr] (ecmascript) <locals>");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/css.mjs [app-ssr] (ecmascript)");
;
;
const TITLE = {
    ambulance: "구급차 대시보드",
    hospital: "병원 대시보드"
};
function DashboardShell({ role, connectionMode, children }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
            minHeight: "100vh",
            backgroundColor: "gray.50"
        }),
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("header", {
                className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "4",
                    borderBottomWidth: "1px",
                    borderColor: "gray.200",
                    backgroundColor: "white"
                }),
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("h1", {
                        className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                            fontSize: "lg",
                            fontWeight: "bold"
                        }),
                        children: [
                            "골든링크 · ",
                            TITLE[role]
                        ]
                    }, void 0, true, {
                        fileName: "[project]/src/components/layout/DashboardShell.tsx",
                        lineNumber: 32,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                            fontSize: "xs",
                            fontWeight: "medium",
                            color: connectionMode === "live" ? "hospitalStatus.confirmed" : "gray.400"
                        }),
                        children: connectionMode === "live" ? "● 실시간 연동" : "○ 목데이터 모드"
                    }, void 0, false, {
                        fileName: "[project]/src/components/layout/DashboardShell.tsx",
                        lineNumber: 35,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/src/components/layout/DashboardShell.tsx",
                lineNumber: 21,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("main", {
                className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                    display: "flex",
                    flexDirection: "column",
                    gap: "4",
                    padding: "6",
                    maxWidth: "960px",
                    marginX: "auto"
                }),
                children: children
            }, void 0, false, {
                fileName: "[project]/src/components/layout/DashboardShell.tsx",
                lineNumber: 45,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/src/components/layout/DashboardShell.tsx",
        lineNumber: 20,
        columnNumber: 5
    }, this);
}
}),
"[project]/src/components/layout/Panel.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "Panel",
    ()=>Panel
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$locals$3e$__ = __turbopack_context__.i("[project]/styled-system/css/index.mjs [app-ssr] (ecmascript) <locals>");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/css.mjs [app-ssr] (ecmascript)");
;
;
function Panel({ title, badge, children }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
        className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
            display: "flex",
            flexDirection: "column",
            gap: "3",
            borderWidth: "1px",
            borderColor: "gray.200",
            borderRadius: "lg",
            backgroundColor: "white",
            padding: "5"
        }),
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("header", {
                className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between"
                }),
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("h2", {
                        className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                            fontSize: "md",
                            fontWeight: "semibold"
                        }),
                        children: title
                    }, void 0, false, {
                        fileName: "[project]/src/components/layout/Panel.tsx",
                        lineNumber: 33,
                        columnNumber: 9
                    }, this),
                    badge
                ]
            }, void 0, true, {
                fileName: "[project]/src/components/layout/Panel.tsx",
                lineNumber: 26,
                columnNumber: 7
            }, this),
            children
        ]
    }, void 0, true, {
        fileName: "[project]/src/components/layout/Panel.tsx",
        lineNumber: 14,
        columnNumber: 5
    }, this);
}
}),
"[project]/styled-system/recipes/create-recipe.mjs [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "createRecipe",
    ()=>createRecipe,
    "mergeRecipes",
    ()=>mergeRecipes
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$conditions$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/conditions.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/css.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$cva$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/cva.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$cx$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/cx.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/helpers.mjs [app-ssr] (ecmascript)");
;
;
;
;
;
const createRecipe = (name, defaultVariants, compoundVariants)=>{
    const getVariantProps = (variants)=>{
        return {
            [name]: '__ignore__',
            ...defaultVariants,
            ...(0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["compact"])(variants)
        };
    };
    const recipeFn = (variants, withCompoundVariants = true)=>{
        const transform = (prop, value)=>{
            (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$cva$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["assertCompoundVariant"])(name, compoundVariants, variants, prop);
            if (value === '__ignore__') {
                return {
                    className: name
                };
            }
            value = (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["withoutSpace"])(value);
            return {
                className: `${name}--${prop}_${value}`
            };
        };
        const recipeCss = (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["createCss"])({
            conditions: {
                shift: __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$conditions$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["sortConditions"],
                finalize: __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$conditions$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["finalizeConditions"],
                breakpoints: {
                    keys: [
                        "base",
                        "sm",
                        "md",
                        "lg",
                        "xl",
                        "2xl"
                    ]
                }
            },
            utility: {
                toHash: (path, hashFn)=>hashFn(path.join(":")),
                transform
            }
        });
        const recipeStyles = getVariantProps(variants);
        if (withCompoundVariants) {
            const compoundVariantStyles = (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$cva$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["getCompoundVariantCss"])(compoundVariants, recipeStyles);
            return (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$cx$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["cx"])(recipeCss(recipeStyles), (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])(compoundVariantStyles));
        }
        return recipeCss(recipeStyles);
    };
    return {
        recipeFn,
        getVariantProps,
        __getCompoundVariantCss__: (variants)=>{
            return (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$cva$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["getCompoundVariantCss"])(compoundVariants, getVariantProps(variants));
        }
    };
};
const mergeRecipes = (recipeA, recipeB)=>{
    if (recipeA && !recipeB) return recipeA;
    if (!recipeA && recipeB) return recipeB;
    const recipeFn = (...args)=>(0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$cx$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["cx"])(recipeA(...args), recipeB(...args));
    const variantKeys = (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["uniq"])(recipeA.variantKeys, recipeB.variantKeys);
    const variantMap = variantKeys.reduce((acc, key)=>{
        acc[key] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["uniq"])(recipeA.variantMap[key], recipeB.variantMap[key]);
        return acc;
    }, {});
    return Object.assign(recipeFn, {
        __recipe__: true,
        __name__: `${recipeA.__name__} ${recipeB.__name__}`,
        raw: (props)=>props,
        variantKeys,
        variantMap,
        splitVariantProps (props) {
            return (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["splitProps"])(props, variantKeys);
        }
    });
};
}),
"[project]/styled-system/recipes/source-badge.mjs [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "sourceBadge",
    ()=>sourceBadge
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/helpers.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$create$2d$recipe$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/recipes/create-recipe.mjs [app-ssr] (ecmascript)");
;
;
const sourceBadgeFn = /* @__PURE__ */ (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$create$2d$recipe$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["createRecipe"])('sourceBadge', {}, []);
const sourceBadgeVariantMap = {
    "source": [
        "ai",
        "rule"
    ]
};
const sourceBadgeVariantKeys = Object.keys(sourceBadgeVariantMap);
const sourceBadge = /* @__PURE__ */ Object.assign((0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["memo"])(sourceBadgeFn.recipeFn), {
    __recipe__: true,
    __name__: 'sourceBadge',
    __getCompoundVariantCss__: sourceBadgeFn.__getCompoundVariantCss__,
    raw: (props)=>props,
    variantKeys: sourceBadgeVariantKeys,
    variantMap: sourceBadgeVariantMap,
    merge (recipe) {
        return (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$create$2d$recipe$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["mergeRecipes"])(this, recipe);
    },
    splitVariantProps (props) {
        return (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["splitProps"])(props, sourceBadgeVariantKeys);
    },
    getVariantProps: sourceBadgeFn.getVariantProps
});
}),
"[project]/styled-system/recipes/severity-badge.mjs [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "severityBadge",
    ()=>severityBadge
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/helpers.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$create$2d$recipe$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/recipes/create-recipe.mjs [app-ssr] (ecmascript)");
;
;
const severityBadgeFn = /* @__PURE__ */ (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$create$2d$recipe$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["createRecipe"])('severityBadge', {}, []);
const severityBadgeVariantMap = {
    "severity": [
        "high",
        "medium",
        "low"
    ]
};
const severityBadgeVariantKeys = Object.keys(severityBadgeVariantMap);
const severityBadge = /* @__PURE__ */ Object.assign((0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["memo"])(severityBadgeFn.recipeFn), {
    __recipe__: true,
    __name__: 'severityBadge',
    __getCompoundVariantCss__: severityBadgeFn.__getCompoundVariantCss__,
    raw: (props)=>props,
    variantKeys: severityBadgeVariantKeys,
    variantMap: severityBadgeVariantMap,
    merge (recipe) {
        return (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$create$2d$recipe$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["mergeRecipes"])(this, recipe);
    },
    splitVariantProps (props) {
        return (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["splitProps"])(props, severityBadgeVariantKeys);
    },
    getVariantProps: severityBadgeFn.getVariantProps
});
}),
"[project]/styled-system/recipes/hospital-status-badge.mjs [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "hospitalStatusBadge",
    ()=>hospitalStatusBadge
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/helpers.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$create$2d$recipe$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/recipes/create-recipe.mjs [app-ssr] (ecmascript)");
;
;
const hospitalStatusBadgeFn = /* @__PURE__ */ (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$create$2d$recipe$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["createRecipe"])('hospitalStatusBadge', {}, []);
const hospitalStatusBadgeVariantMap = {
    "status": [
        "pending",
        "approved",
        "rejected",
        "confirmed"
    ]
};
const hospitalStatusBadgeVariantKeys = Object.keys(hospitalStatusBadgeVariantMap);
const hospitalStatusBadge = /* @__PURE__ */ Object.assign((0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["memo"])(hospitalStatusBadgeFn.recipeFn), {
    __recipe__: true,
    __name__: 'hospitalStatusBadge',
    __getCompoundVariantCss__: hospitalStatusBadgeFn.__getCompoundVariantCss__,
    raw: (props)=>props,
    variantKeys: hospitalStatusBadgeVariantKeys,
    variantMap: hospitalStatusBadgeVariantMap,
    merge (recipe) {
        return (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$create$2d$recipe$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["mergeRecipes"])(this, recipe);
    },
    splitVariantProps (props) {
        return (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$helpers$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["splitProps"])(props, hospitalStatusBadgeVariantKeys);
    },
    getVariantProps: hospitalStatusBadgeFn.getVariantProps
});
}),
"[project]/styled-system/recipes/index.mjs [app-ssr] (ecmascript) <locals>", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([]);
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$source$2d$badge$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/recipes/source-badge.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$severity$2d$badge$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/recipes/severity-badge.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$hospital$2d$status$2d$badge$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/recipes/hospital-status-badge.mjs [app-ssr] (ecmascript)");
;
;
;
}),
"[project]/src/components/badges/SourceBadge.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "SourceBadge",
    ()=>SourceBadge
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$locals$3e$__ = __turbopack_context__.i("[project]/styled-system/recipes/index.mjs [app-ssr] (ecmascript) <locals>");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$source$2d$badge$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/recipes/source-badge.mjs [app-ssr] (ecmascript)");
;
;
const LABEL = {
    ai: "AI 처리",
    rule: "규칙 기반"
};
function SourceBadge({ source }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
        className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$source$2d$badge$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["sourceBadge"])({
            source
        }),
        children: LABEL[source]
    }, void 0, false, {
        fileName: "[project]/src/components/badges/SourceBadge.tsx",
        lineNumber: 9,
        columnNumber: 10
    }, this);
}
}),
"[project]/src/components/badges/SeverityBadge.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "SeverityBadge",
    ()=>SeverityBadge
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$locals$3e$__ = __turbopack_context__.i("[project]/styled-system/recipes/index.mjs [app-ssr] (ecmascript) <locals>");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$severity$2d$badge$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/recipes/severity-badge.mjs [app-ssr] (ecmascript)");
;
;
const LABEL = {
    high: "중증",
    medium: "중등도",
    low: "경증"
};
function SeverityBadge({ severity }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
        className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$severity$2d$badge$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["severityBadge"])({
            severity
        }),
        children: LABEL[severity]
    }, void 0, false, {
        fileName: "[project]/src/components/badges/SeverityBadge.tsx",
        lineNumber: 12,
        columnNumber: 5
    }, this);
}
}),
"[project]/src/components/ui/button-styles.ts [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "inputStyle",
    ()=>inputStyle,
    "primaryButtonStyle",
    ()=>primaryButtonStyle,
    "secondaryButtonStyle",
    ()=>secondaryButtonStyle
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$locals$3e$__ = __turbopack_context__.i("[project]/styled-system/css/index.mjs [app-ssr] (ecmascript) <locals>");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/css.mjs [app-ssr] (ecmascript)");
;
const primaryButtonStyle = (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
    paddingX: "4",
    paddingY: "2",
    borderRadius: "md",
    fontSize: "sm",
    fontWeight: "semibold",
    color: "white",
    backgroundColor: "brand",
    cursor: "pointer",
    _hover: {
        backgroundColor: "brand.emphasis"
    },
    _disabled: {
        opacity: 0.4,
        cursor: "not-allowed"
    }
});
const secondaryButtonStyle = (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
    paddingX: "4",
    paddingY: "2",
    borderRadius: "md",
    fontSize: "sm",
    fontWeight: "medium",
    color: "gray.700",
    backgroundColor: "gray.100",
    cursor: "pointer",
    _hover: {
        backgroundColor: "gray.200"
    },
    _disabled: {
        opacity: 0.4,
        cursor: "not-allowed"
    }
});
const inputStyle = (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
    width: "100%",
    borderWidth: "1px",
    borderColor: "gray.300",
    borderRadius: "md",
    paddingX: "2.5",
    paddingY: "1.5",
    fontSize: "sm",
    _focus: {
        borderColor: "brand",
        outline: "none"
    }
});
}),
"[project]/src/components/panels/CallSummaryPanel.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "CallSummaryPanel",
    ()=>CallSummaryPanel
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$locals$3e$__ = __turbopack_context__.i("[project]/styled-system/css/index.mjs [app-ssr] (ecmascript) <locals>");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/css.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$layout$2f$Panel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/layout/Panel.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$badges$2f$SourceBadge$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/badges/SourceBadge.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$badges$2f$SeverityBadge$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/badges/SeverityBadge.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$ui$2f$button$2d$styles$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/ui/button-styles.ts [app-ssr] (ecmascript)");
"use client";
;
;
;
;
;
;
;
function Field({ label, children }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
            display: "flex",
            flexDirection: "column",
            gap: "1"
        }),
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                    fontSize: "xs",
                    color: "gray.500"
                }),
                children: label
            }, void 0, false, {
                fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                lineNumber: 20,
                columnNumber: 7
            }, this),
            children
        ]
    }, void 0, true, {
        fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
        lineNumber: 19,
        columnNumber: 5
    }, this);
}
function toListInput(values) {
    return values.join(", ");
}
function fromListInput(value) {
    return value.split(",").map((item)=>item.trim()).filter(Boolean);
}
function CallSummaryPanel({ data }) {
    const [editing, setEditing] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    const [draft, setDraft] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(data?.summary ?? null);
    // data가 새로 도착했을 때만 draft를 리셋한다 (렌더링 중 상태 조정 패턴).
    const [syncedData, setSyncedData] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(data);
    if (data !== syncedData) {
        setSyncedData(data);
        setDraft(data?.summary ?? null);
        setEditing(false);
    }
    if (!data || !draft) {
        return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$layout$2f$Panel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["Panel"], {
            title: "통화 요약",
            badge: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$badges$2f$SourceBadge$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["SourceBadge"], {
                source: "ai"
            }, void 0, false, {
                fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                lineNumber: 51,
                columnNumber: 35
            }, this),
            children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                    color: "gray.400",
                    fontSize: "sm"
                }),
                children: "수신 대기 중..."
            }, void 0, false, {
                fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                lineNumber: 52,
                columnNumber: 9
            }, this)
        }, void 0, false, {
            fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
            lineNumber: 51,
            columnNumber: 7
        }, this);
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$layout$2f$Panel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["Panel"], {
        title: "통화 요약",
        badge: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
            className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                display: "flex",
                gap: "2",
                alignItems: "center"
            }),
            children: [
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$badges$2f$SeverityBadge$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["SeverityBadge"], {
                    severity: draft.severity_tag
                }, void 0, false, {
                    fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                    lineNumber: 64,
                    columnNumber: 11
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$badges$2f$SourceBadge$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["SourceBadge"], {
                    source: "ai"
                }, void 0, false, {
                    fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                    lineNumber: 65,
                    columnNumber: 11
                }, this)
            ]
        }, void 0, true, {
            fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
            lineNumber: 63,
            columnNumber: 9
        }, this),
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                    display: "flex",
                    flexDirection: "column",
                    gap: "3"
                }),
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(Field, {
                        label: "환자",
                        children: editing ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                            className: __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$ui$2f$button$2d$styles$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["inputStyle"],
                            value: draft.patient,
                            onChange: (e)=>setDraft({
                                    ...draft,
                                    patient: e.target.value
                                })
                        }, void 0, false, {
                            fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                            lineNumber: 72,
                            columnNumber: 13
                        }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                            children: draft.patient
                        }, void 0, false, {
                            fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                            lineNumber: 78,
                            columnNumber: 13
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                        lineNumber: 70,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(Field, {
                        label: "사고 기전",
                        children: editing ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                            className: __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$ui$2f$button$2d$styles$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["inputStyle"],
                            value: draft.mechanism,
                            onChange: (e)=>setDraft({
                                    ...draft,
                                    mechanism: e.target.value
                                })
                        }, void 0, false, {
                            fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                            lineNumber: 83,
                            columnNumber: 13
                        }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                            children: draft.mechanism
                        }, void 0, false, {
                            fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                            lineNumber: 89,
                            columnNumber: 13
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                        lineNumber: 81,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(Field, {
                        label: "증상",
                        children: editing ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                            className: __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$ui$2f$button$2d$styles$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["inputStyle"],
                            value: toListInput(draft.symptoms),
                            onChange: (e)=>setDraft({
                                    ...draft,
                                    symptoms: fromListInput(e.target.value)
                                })
                        }, void 0, false, {
                            fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                            lineNumber: 94,
                            columnNumber: 13
                        }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                            children: draft.symptoms.join(", ")
                        }, void 0, false, {
                            fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                            lineNumber: 102,
                            columnNumber: 13
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                        lineNumber: 92,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(Field, {
                        label: "처치",
                        children: editing ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                            className: __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$ui$2f$button$2d$styles$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["inputStyle"],
                            value: toListInput(draft.treatment),
                            onChange: (e)=>setDraft({
                                    ...draft,
                                    treatment: fromListInput(e.target.value)
                                })
                        }, void 0, false, {
                            fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                            lineNumber: 107,
                            columnNumber: 13
                        }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                            children: draft.treatment.join(", ")
                        }, void 0, false, {
                            fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                            lineNumber: 115,
                            columnNumber: 13
                        }, this)
                    }, void 0, false, {
                        fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                        lineNumber: 105,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                lineNumber: 69,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                    display: "flex",
                    gap: "2",
                    justifyContent: "flex-end"
                }),
                children: editing ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["Fragment"], {
                    children: [
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                            type: "button",
                            className: __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$ui$2f$button$2d$styles$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["secondaryButtonStyle"],
                            onClick: ()=>{
                                setDraft(data.summary);
                                setEditing(false);
                            },
                            children: "취소"
                        }, void 0, false, {
                            fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                            lineNumber: 123,
                            columnNumber: 13
                        }, this),
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                            type: "button",
                            className: __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$ui$2f$button$2d$styles$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["primaryButtonStyle"],
                            onClick: ()=>setEditing(false),
                            children: "확인 완료"
                        }, void 0, false, {
                            fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                            lineNumber: 133,
                            columnNumber: 13
                        }, this)
                    ]
                }, void 0, true) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                    type: "button",
                    className: __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$ui$2f$button$2d$styles$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["secondaryButtonStyle"],
                    onClick: ()=>setEditing(true),
                    children: "수정 (Override)"
                }, void 0, false, {
                    fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                    lineNumber: 142,
                    columnNumber: 11
                }, this)
            }, void 0, false, {
                fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
                lineNumber: 120,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/src/components/panels/CallSummaryPanel.tsx",
        lineNumber: 60,
        columnNumber: 5
    }, this);
}
}),
"[project]/src/components/panels/VitalsPanel.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "VitalsPanel",
    ()=>VitalsPanel
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$locals$3e$__ = __turbopack_context__.i("[project]/styled-system/css/index.mjs [app-ssr] (ecmascript) <locals>");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/css.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$layout$2f$Panel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/layout/Panel.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$badges$2f$SourceBadge$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/badges/SourceBadge.tsx [app-ssr] (ecmascript)");
;
;
;
;
const VITAL_LABELS = {
    bp_systolic: "수축기 혈압",
    bp_diastolic: "이완기 혈압",
    pulse: "맥박",
    spo2: "산소포화도",
    gcs: "GCS",
    temperature: "체온",
    resp_rate: "호흡수"
};
const VITAL_UNITS = {
    bp_systolic: "mmHg",
    bp_diastolic: "mmHg",
    pulse: "bpm",
    spo2: "%",
    temperature: "℃",
    resp_rate: "회/분"
};
function VitalsPanel({ data }) {
    if (!data) {
        return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$layout$2f$Panel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["Panel"], {
            title: "바이탈",
            badge: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$badges$2f$SourceBadge$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["SourceBadge"], {
                source: "rule"
            }, void 0, false, {
                fileName: "[project]/src/components/panels/VitalsPanel.tsx",
                lineNumber: 30,
                columnNumber: 33
            }, this),
            children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                    color: "gray.400",
                    fontSize: "sm"
                }),
                children: "수신 대기 중..."
            }, void 0, false, {
                fileName: "[project]/src/components/panels/VitalsPanel.tsx",
                lineNumber: 31,
                columnNumber: 9
            }, this)
        }, void 0, false, {
            fileName: "[project]/src/components/panels/VitalsPanel.tsx",
            lineNumber: 30,
            columnNumber: 7
        }, this);
    }
    const keys = Object.keys(data.vitals);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$layout$2f$Panel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["Panel"], {
        title: "바이탈",
        badge: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$badges$2f$SourceBadge$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["SourceBadge"], {
            source: "rule"
        }, void 0, false, {
            fileName: "[project]/src/components/panels/VitalsPanel.tsx",
            lineNumber: 41,
            columnNumber: 31
        }, this),
        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
            className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
                gap: "4"
            }),
            children: keys.map((key)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                    className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                        display: "flex",
                        flexDirection: "column"
                    }),
                    children: [
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                            className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                                fontSize: "xs",
                                color: "gray.500"
                            }),
                            children: VITAL_LABELS[key]
                        }, void 0, false, {
                            fileName: "[project]/src/components/panels/VitalsPanel.tsx",
                            lineNumber: 51,
                            columnNumber: 13
                        }, this),
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                            className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                                fontSize: "lg",
                                fontWeight: "semibold"
                            }),
                            children: [
                                data.vitals[key],
                                VITAL_UNITS[key] ? ` ${VITAL_UNITS[key]}` : ""
                            ]
                        }, void 0, true, {
                            fileName: "[project]/src/components/panels/VitalsPanel.tsx",
                            lineNumber: 54,
                            columnNumber: 13
                        }, this)
                    ]
                }, key, true, {
                    fileName: "[project]/src/components/panels/VitalsPanel.tsx",
                    lineNumber: 50,
                    columnNumber: 11
                }, this))
        }, void 0, false, {
            fileName: "[project]/src/components/panels/VitalsPanel.tsx",
            lineNumber: 42,
            columnNumber: 7
        }, this)
    }, void 0, false, {
        fileName: "[project]/src/components/panels/VitalsPanel.tsx",
        lineNumber: 41,
        columnNumber: 5
    }, this);
}
}),
"[project]/src/components/badges/HospitalStatusBadge.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "HospitalStatusBadge",
    ()=>HospitalStatusBadge
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$locals$3e$__ = __turbopack_context__.i("[project]/styled-system/recipes/index.mjs [app-ssr] (ecmascript) <locals>");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$hospital$2d$status$2d$badge$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/recipes/hospital-status-badge.mjs [app-ssr] (ecmascript)");
;
;
const LABEL = {
    pending: "대기중",
    approved: "후보 등록",
    rejected: "거절",
    confirmed: "이송 확정"
};
function HospitalStatusBadge({ status }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
        className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$recipes$2f$hospital$2d$status$2d$badge$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["hospitalStatusBadge"])({
            status
        }),
        children: LABEL[status]
    }, void 0, false, {
        fileName: "[project]/src/components/badges/HospitalStatusBadge.tsx",
        lineNumber: 13,
        columnNumber: 5
    }, this);
}
}),
"[project]/src/components/panels/HospitalListPanel.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "HospitalListPanel",
    ()=>HospitalListPanel
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$locals$3e$__ = __turbopack_context__.i("[project]/styled-system/css/index.mjs [app-ssr] (ecmascript) <locals>");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/css.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$layout$2f$Panel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/layout/Panel.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$badges$2f$SourceBadge$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/badges/SourceBadge.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$badges$2f$HospitalStatusBadge$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/badges/HospitalStatusBadge.tsx [app-ssr] (ecmascript)");
;
;
;
;
;
function HospitalListPanel({ data, selectedHospitalId, onSelect }) {
    if (!data) {
        return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$layout$2f$Panel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["Panel"], {
            title: "병원 매칭",
            badge: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$badges$2f$SourceBadge$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["SourceBadge"], {
                source: "rule"
            }, void 0, false, {
                fileName: "[project]/src/components/panels/HospitalListPanel.tsx",
                lineNumber: 18,
                columnNumber: 35
            }, this),
            children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("p", {
                className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                    color: "gray.400",
                    fontSize: "sm"
                }),
                children: "수신 대기 중..."
            }, void 0, false, {
                fileName: "[project]/src/components/panels/HospitalListPanel.tsx",
                lineNumber: 19,
                columnNumber: 9
            }, this)
        }, void 0, false, {
            fileName: "[project]/src/components/panels/HospitalListPanel.tsx",
            lineNumber: 18,
            columnNumber: 7
        }, this);
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$layout$2f$Panel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["Panel"], {
        title: `병원 매칭 · Zone ${data.zone_active.join(", ")}`,
        badge: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$badges$2f$SourceBadge$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["SourceBadge"], {
            source: "rule"
        }, void 0, false, {
            fileName: "[project]/src/components/panels/HospitalListPanel.tsx",
            lineNumber: 29,
            columnNumber: 14
        }, this),
        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("ul", {
            className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                display: "flex",
                flexDirection: "column",
                gap: "2"
            }),
            children: data.hospitals.map((hospital)=>{
                const selected = hospital.hospital_id === selectedHospitalId;
                const selectable = Boolean(onSelect) && hospital.status !== "rejected";
                return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("li", {
                    children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                        type: "button",
                        disabled: !selectable,
                        onClick: ()=>onSelect?.(hospital.hospital_id),
                        className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                            width: "100%",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            padding: "3",
                            borderRadius: "md",
                            borderWidth: "1px",
                            borderColor: selected ? "brand" : "gray.200",
                            backgroundColor: selected ? "amber.50" : "white",
                            cursor: selectable ? "pointer" : "default",
                            textAlign: "left",
                            _disabled: {
                                opacity: 0.5
                            }
                        }),
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                                    display: "flex",
                                    flexDirection: "column"
                                }),
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                                            fontWeight: "medium"
                                        }),
                                        children: hospital.name
                                    }, void 0, false, {
                                        fileName: "[project]/src/components/panels/HospitalListPanel.tsx",
                                        lineNumber: 58,
                                        columnNumber: 19
                                    }, this),
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                                            fontSize: "xs",
                                            color: "gray.500"
                                        }),
                                        children: [
                                            hospital.distance_km,
                                            "km",
                                            hospital.eta_min != null ? ` · ETA ${hospital.eta_min}분` : ""
                                        ]
                                    }, void 0, true, {
                                        fileName: "[project]/src/components/panels/HospitalListPanel.tsx",
                                        lineNumber: 59,
                                        columnNumber: 19
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/src/components/panels/HospitalListPanel.tsx",
                                lineNumber: 57,
                                columnNumber: 17
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$badges$2f$HospitalStatusBadge$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["HospitalStatusBadge"], {
                                status: hospital.status
                            }, void 0, false, {
                                fileName: "[project]/src/components/panels/HospitalListPanel.tsx",
                                lineNumber: 64,
                                columnNumber: 17
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/src/components/panels/HospitalListPanel.tsx",
                        lineNumber: 38,
                        columnNumber: 15
                    }, this)
                }, hospital.hospital_id, false, {
                    fileName: "[project]/src/components/panels/HospitalListPanel.tsx",
                    lineNumber: 37,
                    columnNumber: 13
                }, this);
            })
        }, void 0, false, {
            fileName: "[project]/src/components/panels/HospitalListPanel.tsx",
            lineNumber: 31,
            columnNumber: 7
        }, this)
    }, void 0, false, {
        fileName: "[project]/src/components/panels/HospitalListPanel.tsx",
        lineNumber: 27,
        columnNumber: 5
    }, this);
}
}),
"[project]/src/components/panels/ApprovalActions.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "ApprovalActions",
    ()=>ApprovalActions
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$index$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__$3c$locals$3e$__ = __turbopack_context__.i("[project]/styled-system/css/index.mjs [app-ssr] (ecmascript) <locals>");
var __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/styled-system/css/css.mjs [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$ui$2f$button$2d$styles$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/ui/button-styles.ts [app-ssr] (ecmascript)");
"use client";
;
;
;
function ApprovalActions({ role, hospitalId, onAction }) {
    const disabled = !hospitalId;
    function dispatch(action, actor) {
        if (!hospitalId) return;
        onAction({
            action,
            hospital_id: hospitalId,
            actor,
            timestamp: new Date().toISOString()
        });
    }
    if (role === "hospital") {
        return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
            className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
                display: "flex",
                gap: "2",
                justifyContent: "flex-end"
            }),
            children: [
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                    type: "button",
                    disabled: disabled,
                    className: __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$ui$2f$button$2d$styles$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["secondaryButtonStyle"],
                    onClick: ()=>dispatch("hospital_reject", "hospital"),
                    children: "병원 불가"
                }, void 0, false, {
                    fileName: "[project]/src/components/panels/ApprovalActions.tsx",
                    lineNumber: 30,
                    columnNumber: 9
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                    type: "button",
                    disabled: disabled,
                    className: __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$ui$2f$button$2d$styles$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["primaryButtonStyle"],
                    onClick: ()=>dispatch("hospital_approve", "hospital"),
                    children: "병원 승인"
                }, void 0, false, {
                    fileName: "[project]/src/components/panels/ApprovalActions.tsx",
                    lineNumber: 38,
                    columnNumber: 9
                }, this)
            ]
        }, void 0, true, {
            fileName: "[project]/src/components/panels/ApprovalActions.tsx",
            lineNumber: 29,
            columnNumber: 7
        }, this);
    }
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        className: (0, __TURBOPACK__imported__module__$5b$project$5d2f$styled$2d$system$2f$css$2f$css$2e$mjs__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["css"])({
            display: "flex",
            justifyContent: "flex-end"
        }),
        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
            type: "button",
            disabled: disabled,
            className: __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$ui$2f$button$2d$styles$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["primaryButtonStyle"],
            onClick: ()=>dispatch("final_approval", "paramedic"),
            children: "이송 승인"
        }, void 0, false, {
            fileName: "[project]/src/components/panels/ApprovalActions.tsx",
            lineNumber: 52,
            columnNumber: 7
        }, this)
    }, void 0, false, {
        fileName: "[project]/src/components/panels/ApprovalActions.tsx",
        lineNumber: 51,
        columnNumber: 5
    }, this);
}
}),
"[project]/src/lib/mock-data.ts [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "mockCallSummary",
    ()=>mockCallSummary,
    "mockHospitalMatch",
    ()=>mockHospitalMatch,
    "mockVitals",
    ()=>mockVitals
]);
const mockCallSummary = {
    transcript: {
        raw_text: "구급대원: 환자 50대 남성, 교통사고 흉부 충격입니다... A병원: 네 잠시만요...",
        filtered_text: "환자 50대 남성, 교통사고 흉부 충격. 의식 저하, 호흡 곤란.",
        language: "ko",
        timestamp: "2026-07-28T14:32:31Z",
        duration_sec: 42.3
    },
    summary: {
        patient: "50대 남성",
        mechanism: "교통사고 · 흉부 충격",
        symptoms: [
            "의식 저하",
            "호흡 곤란"
        ],
        treatment: [
            "산소 공급",
            "지혈 완료"
        ],
        severity_tag: "high"
    },
    source: "ai",
    model_used: {
        stt: "faster-whisper-large-v3",
        llm: "qwen3:14b"
    }
};
const mockVitals = {
    vitals: {
        bp_systolic: 90,
        bp_diastolic: 60,
        pulse: 102,
        spo2: 92,
        gcs: 13,
        temperature: 36.4,
        resp_rate: 24
    },
    timestamp: "2026-07-28T14:33:10Z",
    source: "rule"
};
const mockHospitalMatch = {
    zone_active: [
        1,
        2
    ],
    hospitals: [
        {
            hospital_id: "A",
            name: "A병원",
            distance_km: 1.4,
            status: "pending"
        },
        {
            hospital_id: "B",
            name: "B병원",
            distance_km: 1.9,
            status: "approved",
            eta_min: 5
        },
        {
            hospital_id: "C",
            name: "C병원",
            distance_km: 2.1,
            status: "confirmed",
            eta_min: 6
        },
        {
            hospital_id: "D",
            name: "D병원",
            distance_km: 2.6,
            status: "rejected"
        }
    ],
    source: "rule"
};
}),
"[project]/src/hooks/use-dashboard-socket.ts [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "useDashboardSocket",
    ()=>useDashboardSocket
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$lib$2f$mock$2d$data$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/lib/mock-data.ts [app-ssr] (ecmascript)");
"use client";
;
;
const INITIAL_STATE = {
    callSummary: null,
    vitals: null,
    hospitalMatch: null
};
// voice/vital 브랜치는 아직 WS 서버가 없다. NEXT_PUBLIC_DASHBOARD_WS_URL이
// 설정되지 않으면 목데이터를 순차적으로 흘려보내 화면 작업을 진행할 수 있게 한다.
function applyInboundMessage(state, message) {
    if ("transcript" in message) {
        return {
            ...state,
            callSummary: message
        };
    }
    if ("vitals" in message) {
        return {
            ...state,
            vitals: message
        };
    }
    if ("hospitals" in message) {
        return {
            ...state,
            hospitalMatch: message
        };
    }
    return state;
}
function useDashboardSocket() {
    const [state, setState] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(INITIAL_STATE);
    const [connectionMode, setConnectionMode] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])("mock");
    const socketRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useRef"])(null);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        const wsUrl = process.env.NEXT_PUBLIC_DASHBOARD_WS_URL;
        if (!wsUrl) {
            // 완료된 정보부터 순차적으로 갱신 (CLAUDE.md 실시간 갱신 원칙)
            const timers = [
                setTimeout(()=>setState((prev)=>applyInboundMessage(prev, __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$lib$2f$mock$2d$data$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["mockCallSummary"])), 600),
                setTimeout(()=>setState((prev)=>applyInboundMessage(prev, __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$lib$2f$mock$2d$data$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["mockVitals"])), 1400),
                setTimeout(()=>setState((prev)=>applyInboundMessage(prev, __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$lib$2f$mock$2d$data$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["mockHospitalMatch"])), 2200)
            ];
            return ()=>timers.forEach(clearTimeout);
        }
        const socket = new WebSocket(wsUrl);
        socketRef.current = socket;
        socket.onopen = ()=>setConnectionMode("live");
        socket.onclose = ()=>setConnectionMode("mock");
        socket.onerror = ()=>setConnectionMode("mock");
        socket.onmessage = (event)=>{
            try {
                const parsed = JSON.parse(event.data);
                setState((prev)=>applyInboundMessage(prev, parsed));
            } catch  {
            // 파싱 불가능한 메시지는 무시
            }
        };
        return ()=>socket.close();
    }, []);
    const sendAction = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((action)=>{
        const socket = socketRef.current;
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify(action));
        } else {
            console.info("[mock] 승인 액션 전송(WS 미연결):", action);
        }
    }, []);
    return {
        state,
        connectionMode,
        sendAction
    };
}
}),
"[project]/src/app/ambulance/page.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "default",
    ()=>AmbulanceDashboardPage
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$layout$2f$DashboardShell$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/layout/DashboardShell.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$panels$2f$CallSummaryPanel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/panels/CallSummaryPanel.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$panels$2f$VitalsPanel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/panels/VitalsPanel.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$panels$2f$HospitalListPanel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/panels/HospitalListPanel.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$panels$2f$ApprovalActions$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/panels/ApprovalActions.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$hooks$2f$use$2d$dashboard$2d$socket$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/hooks/use-dashboard-socket.ts [app-ssr] (ecmascript)");
"use client";
;
;
;
;
;
;
;
;
function AmbulanceDashboardPage() {
    const { state, connectionMode, sendAction } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$hooks$2f$use$2d$dashboard$2d$socket$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useDashboardSocket"])();
    const [selectedHospitalId, setSelectedHospitalId] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(null);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$layout$2f$DashboardShell$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["DashboardShell"], {
        role: "ambulance",
        connectionMode: connectionMode,
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$panels$2f$CallSummaryPanel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["CallSummaryPanel"], {
                data: state.callSummary
            }, void 0, false, {
                fileName: "[project]/src/app/ambulance/page.tsx",
                lineNumber: 17,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$panels$2f$VitalsPanel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["VitalsPanel"], {
                data: state.vitals
            }, void 0, false, {
                fileName: "[project]/src/app/ambulance/page.tsx",
                lineNumber: 18,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$panels$2f$HospitalListPanel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["HospitalListPanel"], {
                data: state.hospitalMatch,
                selectedHospitalId: selectedHospitalId,
                onSelect: setSelectedHospitalId
            }, void 0, false, {
                fileName: "[project]/src/app/ambulance/page.tsx",
                lineNumber: 19,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$panels$2f$ApprovalActions$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["ApprovalActions"], {
                role: "ambulance",
                hospitalId: selectedHospitalId,
                onAction: sendAction
            }, void 0, false, {
                fileName: "[project]/src/app/ambulance/page.tsx",
                lineNumber: 24,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/src/app/ambulance/page.tsx",
        lineNumber: 16,
        columnNumber: 5
    }, this);
}
}),
];

//# sourceMappingURL=_0uiezd-._.js.map