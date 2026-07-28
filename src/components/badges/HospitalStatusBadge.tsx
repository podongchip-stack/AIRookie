import { hospitalStatusBadge } from "styled-system/recipes";
import type { HospitalStatus } from "@/types/dashboard";

const LABEL: Record<HospitalStatus, string> = {
  pending: "대기중",
  approved: "후보 등록",
  rejected: "거절",
  confirmed: "이송 확정",
};

export function HospitalStatusBadge({ status }: { status: HospitalStatus }) {
  return (
    <span className={hospitalStatusBadge({ status })}>{LABEL[status]}</span>
  );
}
