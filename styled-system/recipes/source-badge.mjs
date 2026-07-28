import { memo, splitProps } from '../helpers.mjs';
import { createRecipe, mergeRecipes } from './create-recipe.mjs';

const sourceBadgeFn = /* @__PURE__ */ createRecipe('sourceBadge', {}, [])

const sourceBadgeVariantMap = {
  "source": [
    "ai",
    "rule"
  ]
}

const sourceBadgeVariantKeys = Object.keys(sourceBadgeVariantMap)

export const sourceBadge = /* @__PURE__ */ Object.assign(memo(sourceBadgeFn.recipeFn), {
  __recipe__: true,
  __name__: 'sourceBadge',
  __getCompoundVariantCss__: sourceBadgeFn.__getCompoundVariantCss__,
  raw: (props) => props,
  variantKeys: sourceBadgeVariantKeys,
  variantMap: sourceBadgeVariantMap,
  merge(recipe) {
    return mergeRecipes(this, recipe)
  },
  splitVariantProps(props) {
    return splitProps(props, sourceBadgeVariantKeys)
  },
  getVariantProps: sourceBadgeFn.getVariantProps,
})