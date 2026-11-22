"use client";

import { useEffect, useState } from "react";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export interface SessionState {
  ready: boolean;
  userId: string | null;
  email: string | null;
}

/** Current Supabase session (client side). `ready` is false until the first check completes. */
export function useSession(): SessionState {
  const [state, setState] = useState<SessionState>({ ready: false, userId: null, email: null });
  useEffect(() => {
    const sb = getSupabaseBrowserClient();
    if (!sb) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- no client to subscribe to
      setState({ ready: true, userId: null, email: null });
      return;
    }
    sb.auth.getSession().then(({ data }) =>
      setState({ ready: true, userId: data.session?.user.id ?? null, email: data.session?.user.email ?? null }),
    );
    const { data: sub } = sb.auth.onAuthStateChange((_e, session) =>
      setState({ ready: true, userId: session?.user.id ?? null, email: session?.user.email ?? null }),
    );
    return () => sub.subscription.unsubscribe();
  }, []);
  return state;
}
