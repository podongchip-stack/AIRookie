import { memo, splitProps } from '../helpers.mjs';
import { createRecipe, mergeRecipes } from './create-recipe.mjs';

const severityBadgeFn = /* @__PURE__ */ createRecipe('severityBadge', {}, [])

const severityBadgeVariantMap = {
  "severity": [
    "high",
    "medium",
    "low"
  ]
}

const severityBadgeVariantKeys = Object.keys(severityBadgeVariantMap)

export const severityBadge = /* @__PURE__ */ Object.assign(memo(severityBadgeFn.recipeFn), {
  __recipe__: true,
  __name__: 'severityBadge',
  __getCompoundVariantCss__: severityBadgeFn.__getCompoundVariantCss__,
  raw: (props) => props,
  variantKeys: severityBadgeVariantKeys,
  variantMap: severityBadgeVariantMap,
  merge(recipe) {
    return mergeRecipes(this, recipe)
  },
  splitVariantProps(props) {
    return splitProps(props, severityBadgeVariantKeys)
  },
  getVariantProps: severityBadgeFn.getVariantProps,
})