/* eslint-disable */
import type { ConditionalValue } from '../types/index';
import type { DistributiveOmit, Pretty } from '../types/system-types';

interface HospitalStatusBadgeVariant {
  status: "pending" | "approved" | "rejected" | "confirmed"
}

type HospitalStatusBadgeVariantMap = {
  [key in keyof HospitalStatusBadgeVariant]: Array<HospitalStatusBadgeVariant[key]>
}



export type HospitalStatusBadgeVariantProps = {
  [key in keyof HospitalStatusBadgeVariant]?: ConditionalValue<HospitalStatusBadgeVariant[key]> | undefined
}

export interface HospitalStatusBadgeRecipe {
  
  __type: HospitalStatusBadgeVariantProps
  (props?: HospitalStatusBadgeVariantProps): string
  raw: (props?: HospitalStatusBadgeVariantProps) => HospitalStatusBadgeVariantProps
  variantMap: HospitalStatusBadgeVariantMap
  variantKeys: Array<keyof HospitalStatusBadgeVariant>
  splitVariantProps<Props extends HospitalStatusBadgeVariantProps>(props: Props): [HospitalStatusBadgeVariantProps, Pretty<DistributiveOmit<Props, keyof HospitalStatusBadgeVariantProps>>]
  getVariantProps: (props?: HospitalStatusBadgeVariantProps) => HospitalStatusBadgeVariantProps
}


export declare const hospitalStatusBadge: HospitalStatusBadgeRecipe