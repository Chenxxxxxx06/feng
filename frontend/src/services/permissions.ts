import { useAuthStore } from './authStore';

export type AppRole = 'viewer' | 'operator' | 'technician' | 'engineer' | 'approver' | 'admin';

const ROLE_LEVEL: Record<AppRole, number> = {
  viewer: 0,
  operator: 1,
  technician: 1,
  engineer: 2,
  approver: 3,
  admin: 4,
};

export function hasMinimumRole(role: string | null | undefined, minimum: AppRole): boolean {
  const level = ROLE_LEVEL[role as AppRole];
  return typeof level === 'number' && level >= ROLE_LEVEL[minimum];
}

export function useHasMinimumRole(minimum: AppRole): boolean {
  return useAuthStore((state) => hasMinimumRole(state.user?.role, minimum));
}

export const READ_ONLY_PERMISSION_TITLE = '当前账号为只读角色，需要运维人员权限';
