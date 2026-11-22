import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import en from "@/messages/en.json";

export function renderWithIntl(ui: ReactElement, locale = "en", messages: object = en) {
  return render(
    <NextIntlClientProvider locale={locale} messages={messages as never}>
      {ui}
    </NextIntlClientProvider>,
  );
}
