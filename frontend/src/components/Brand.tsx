/** Shared product identity: artwork, typography, and accessible name. */
export const APP_NAME = 'Stavatech Prism Dashboard';
export const BRAND_MARK = '/stavatech-prism-logo.png';

export function BrandMark({className=''}:{className?:string}) {
  return <img className={`prism-brand-artwork ${className}`} src={BRAND_MARK} width={48} height={48} alt="" aria-hidden="true" decoding="async"/>;
}

export function BrandWordmark({compact=false}:{compact?:boolean}) {
  return <span className={`brand-wordmark ${compact?'is-compact':''}`} aria-hidden="true"><span className="brand-company">Stavatech</span><span className="brand-product">Prism <span>Dashboard</span></span></span>;
}
