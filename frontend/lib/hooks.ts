"use client";

import { useQuery } from "@tanstack/react-query";
import { get } from "./api";
import type { Agent, Chat, Model, Page, Provider, User, UserSettings } from "./types";

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => get<User>("/auth/me"), retry: false });
export const useProviders = () =>
  useQuery({
    queryKey: ["providers"],
    queryFn: () => get<Provider[]>("/providers"),
    refetchInterval: 30_000,
  });
export const useModels = (all = false) =>
  useQuery({
    queryKey: ["models", all],
    queryFn: () => get<Model[]>(`/models${all ? "?include_all=true" : ""}`),
  });
export const useAgents = () => useQuery({ queryKey: ["agents"], queryFn: () => get<Agent[]>("/agents") });
export const useChats = () =>
  useQuery({ queryKey: ["chats"], queryFn: () => get<Page<Chat>>("/chats?limit=100") });
export const useSettings = () =>
  useQuery({ queryKey: ["settings"], queryFn: () => get<UserSettings>("/settings") });
