import type { ModelOption } from "./types";
import type { Translator } from "./i18n";

export const REFRESH_MODELS = "__decky_refresh_models__";
export function modelOptions(models: ModelOption[], selected: string, resolved: string | undefined, t: Translator) {
  const recommended = models.find(model => model.is_default);
  const automatic = resolved || recommended?.display_name;
  const options = [{ data: "", label: automatic ? t("默认 · {model}", { model: automatic }) : t("自动选择") }];
  if (selected && !models.some(model => model.model === selected)) options.push({ data: selected, label: selected });
  for (const model of models) options.push({ data: model.model, label: model.display_name || model.model });
  return options;
}
