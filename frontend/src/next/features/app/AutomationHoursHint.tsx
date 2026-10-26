import { useAutomationHours } from "../editor/api";

/** Says so when scheduled automation is outside its allowed hours right now. */
export function AutomationHoursHint() {
  const { data } = useAutomationHours();
  if (!data?.hours || data.open_now) return null;
  return (
    <p className="text-xs text-warning" role="note">
      当前不在自动化时段（{data.hours}）内：定时任务会推迟到时段内，手动触发不受影响，点按钮会立即开始。
    </p>
  );
}
