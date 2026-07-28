/* eslint-disable */
import type { ConditionalValue } from '../types/index';
import type { DistributiveOmit, Pretty } from '../types/system-types';

interface SeverityBadgeVariant {
  severity: "high" | "medium" | "low"
}

type SeverityBadgeVariantMap = {
  [key in keyof SeverityBadgeVariant]: Array<SeverityBadgeVariant[key]>
}



export type SeverityBadgeVariantProps = {
  [key in keyof SeverityBadgeVariant]?: ConditionalValue<SeverityBadgeVariant[key]> | undefined
}

export interface SeverityBadgeRecipe {
  
  __type: SeverityBadgeVariantProps
  (props?: SeverityBadgeVariantProps): string
  raw: (props?: SeverityBadgeVariantProps) => SeverityBadgeVariantProps
  variantMap: SeverityBadgeVariantMap
  variantKeys: Array<keyof SeverityBadgeVariant>
  splitVariantProps<Props extends SeverityBadgeVariantProps>(props: Props): [SeverityBadgeVariantProps, Pretty<DistributiveOmit<Props, keyof SeverityBadgeVariantProps>>]
  getVariantProps: (props?: SeverityBadgeVariantProps) => SeverityBadgeVariantProps
}


export declare const severityBadge: SeverityBadgeRecipe