import { useCallback, useEffect, useState } from "react";
import { api, type LaunchMode, type Profile, type ProfileCreateData } from "../lib/api";

export function useProfiles() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.listProfiles();
      setProfiles(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "获取配置失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    // Poll for status changes every 3 seconds
    const interval = setInterval(refresh, 3000);
    return () => clearInterval(interval);
  }, [refresh]);

  const create = useCallback(
    async (data: ProfileCreateData): Promise<Profile | undefined> => {
      try {
        const profile = await api.createProfile(data);
        setProfiles((prev) => [profile, ...prev]);
        return profile;
      } catch (err) {
        setError(err instanceof Error ? err.message : "创建配置失败");
      }
    },
    [],
  );

  const update = useCallback(
    async (id: string, data: Partial<ProfileCreateData>) => {
      try {
        const profile = await api.updateProfile(id, data);
        setProfiles((prev) => prev.map((p) => (p.id === id ? profile : p)));
        return profile;
      } catch (err) {
        setError(err instanceof Error ? err.message : "保存配置失败");
      }
    },
    [],
  );

  const remove = useCallback(
    async (id: string) => {
      try {
        await api.deleteProfile(id);
        setProfiles((prev) => prev.filter((p) => p.id !== id));
      } catch (err) {
        setError(err instanceof Error ? err.message : "删除配置失败");
      }
    },
    [],
  );

  const launch = useCallback(
    async (id: string, launchMode: LaunchMode = "manual") => {
      try {
        const result = await api.launchProfile(id, launchMode);
        await refresh();
        return result;
      } catch (err) {
        setError(err instanceof Error ? err.message : "启动配置失败");
      }
    },
    [refresh],
  );

  const stop = useCallback(
    async (id: string) => {
      try {
        await api.stopProfile(id);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : "停止配置失败");
      }
    },
    [refresh],
  );

  return { profiles, loading, error, refresh, create, update, remove, launch, stop };
}
