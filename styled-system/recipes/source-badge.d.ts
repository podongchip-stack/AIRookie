/* eslint-disable */
import type { ConditionalValue } from '../types/index';
import type { DistributiveOmit, Pretty } from '../types/system-types';

interface SourceBadgeVariant {
  source: "ai" | "rule"
}

type SourceBadgeVariantMap = {
  [key in keyof SourceBadgeVariant]: Array<SourceBadgeVariant[key]>
}



export type SourceBadgeVariantProps = {
  [key in keyof SourceBadgeVariant]?: ConditionalValue<SourceBadgeVariant[key]> | undefined
}

export interface SourceBadgeRecipe {
  
  __type: SourceBadgeVariantProps
  (props?: SourceBadgeVariantProps): string
  raw: (props?: SourceBadgeVariantProps) => SourceBadgeVariantProps
  variantMap: SourceBadgeVariantMap
  variantKeys: Array<keyof SourceBadgeVariant>
  splitVariantProps<Props extends SourceBadgeVariantProps>(props: Props): [SourceBadgeVariantProps, Pretty<DistributiveOmit<Props, keyof SourceBadgeVariantProps>>]
  getVariantProps: (props?: SourceBadgeVariantProps) => SourceBadgeVariantProps
}


export declare const sourceBadge: SourceBadgeRecipe