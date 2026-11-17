"use client";

import type { FormEvent } from "react";
import { SearchIcon } from "./icons";

interface SearchBoxProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  id?: string;
  placeholder?: string;
}

export function SearchBox({
  value,
  onChange,
  onSubmit,
  id = "library-search",
  placeholder = "Search your library",
}: SearchBoxProps) {
  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <form className="search" role="search" onSubmit={submit}>
      <SearchIcon className="icon search__icon" />
      <label className="sr-only" htmlFor={id}>
        Search your library
      </label>
      <input
        id={id}
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        autoComplete="off"
      />
      <button className="btn btn--primary search__submit" type="submit" disabled={!value.trim()}>
        Search
      </button>
    </form>
  );
}
