/** Fixed product configuration. Empty URLs remain visibly unavailable. */
export const PRODUCT_LINKS: {
  tokensAnywhereUrl: string
  desktopDownloadUrl: string
  landingPageUrl: string
  downloadPageUrl: string
  androidDownloadUrl: string
  iosDownloadUrl: string
  webAppHref: string
} = {
  // Tokens Anywhere's site origin, set with NEXT_PUBLIC_TOKENS_ANYWHERE_URL.
  tokensAnywhereUrl: process.env.NEXT_PUBLIC_TOKENS_ANYWHERE_URL ?? '',
  desktopDownloadUrl: '',
  landingPageUrl: '',
  downloadPageUrl: 'https://github.com/zzyyaa916/Agents-Anywhere/releases',
  androidDownloadUrl: 'https://github.com/zzyyaa916/Agents-Anywhere/releases',
  iosDownloadUrl: '',
  webAppHref: '#/',
}
