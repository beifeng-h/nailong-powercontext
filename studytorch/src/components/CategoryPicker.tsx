"use client";

import { useId, useState } from "react";

const CUSTOM = "__custom__";

interface CategoryPickerProps {
  options: string[];
  value: string;
  onChange: (value: string) => void;
  label?: string;
  /** 首页上传需要能新建分类；结果页筛选只需要在已有分类里选。 */
  allowCustom?: boolean;
  placeholder?: string;
}

export default function CategoryPicker({
  options,
  value,
  onChange,
  label = "分类",
  allowCustom = false,
  placeholder = "全部分类",
}: CategoryPickerProps) {
  const id = useId();
  const [customMode, setCustomMode] = useState(allowCustom && value !== "" && !options.includes(value));
  const selectValue = customMode ? CUSTOM : value;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <label htmlFor={id} className="shrink-0 text-sm text-slate-600">
        {label}
      </label>
      <select
        id={id}
        className="input w-auto"
        value={selectValue}
        onChange={(event) => {
          const next = event.target.value;
          if (next === CUSTOM) {
            setCustomMode(true);
            return;
          }
          setCustomMode(false);
          onChange(next);
        }}
      >
        <option value="">{placeholder}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
        {allowCustom && <option value={CUSTOM}>自定义…</option>}
      </select>
      {customMode && (
        <input
          className="input w-44"
          aria-label="新分类名称"
          placeholder="输入分类名称"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </div>
  );
}
