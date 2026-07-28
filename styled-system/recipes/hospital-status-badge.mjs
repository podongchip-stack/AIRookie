import { memo, splitProps } from '../helpers.mjs';
import { createRecipe, mergeRecipes } from './create-recipe.mjs';

const hospitalStatusBadgeFn = /* @__PURE__ */ createRecipe('hospitalStatusBadge', {}, [])

const hospitalStatusBadgeVariantMap = {
  "status": [
    "pending",
    "approved",
    "rejected",
    "confirmed"
  ]
}

const hospitalStatusBadgeVariantKeys = Object.keys(hospitalStatusBadgeVariantMap)

export const hospitalStatusBadge = /* @__PURE__ */ Object.assign(memo(hospitalStatusBadgeFn.recipeFn), {
  __recipe__: true,
  __name__: 'hospitalStatusBadge',
  __getCompoundVariantCss__: hospitalStatusBadgeFn.__getCompoundVariantCss__,
  raw: (props) => props,
  variantKeys: hospitalStatusBadgeVariantKeys,
  variantMap: hospitalStatusBadgeVariantMap,
  merge(recipe) {
    return mergeRecipes(this, recipe)
  },
  splitVariantProps(props) {
    return splitProps(props, hospitalStatusBadgeVariantKeys)
  },
  getVariantProps: hospitalStatusBadgeFn.getVariantProps,
})