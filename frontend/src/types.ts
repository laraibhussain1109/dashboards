export interface Column {name:string;type:string;missing?:number;unique?:number;[key:string]:any}
export interface Dataset {id:string;name:string;source_type:string;row_count:number;columns:Column[];profile?:any;preview?:Record<string,any>[];version?:number;page?:number;total_pages?:number;[key:string]:any}
export interface Theme {mode?:string;background?:string;surface?:string;text?:string;accent?:string;palette?:string[];font?:string;[key:string]:any}
export interface Widget {id:string;type:string;title:string;dataset_id?:string;layout:{x:number;y:number;w:number;h:number};x?:string;y?:string;series?:string;aggregation?:string;formula?:string;[key:string]:any}
export interface DashboardConfig {widgets:Widget[];theme:Theme;grid?:{columns?:number;gap?:number;rowHeight?:number;padding?:number;[key:string]:any};[key:string]:any}
export interface Dashboard {id:string;title:string;description?:string;config:DashboardConfig;revision:number;published_slug?:string|null;published_at?:string|null;updated_at?:string;[key:string]:any}
export interface QueryResult {labels:any[];series:{name:string;values:any[]}[];value?:number|null;rows:Record<string,any>[];columns:string[];[key:string]:any}
export interface Recommendation extends Partial<Widget> {id:string;title:string;type:string;reason:string;score:number;group:string;[key:string]:any}
