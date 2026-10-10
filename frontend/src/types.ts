import type {Configuration} from './SettingsView';
export type Action=(key:string,fn:()=>Promise<unknown>,message?:string)=>Promise<void>;
export interface Application {source_application_id:string;company:string;role:string;job_url:string;company_website:string;locations:string[];source_status:string;hiring_outcome:string;outcome_note:string;research_state:string;first_seen:string;submitted_at:string;job_description:string;role_candidate?:RoleCandidate;job?:{state:string;stage:string;error:string;next_attempt:number};historical:number;selected:number;source_created_at:string}
export interface RoleCandidate {role:string;method:string;source_url:string;application_id:string;company:string}
export interface Contact {id:number;application_id:string;name:string;title:string;company:string;application_company:string;role:string;linkedin_url:string;dismissed:boolean;review_status:string;review_source:string;review_note:string;source_status:string;hiring_outcome:string;note:string;dm:string;support:{label:string;scope:string};relevance_assessment:{level:string;explanation:string};relevance:string;uncertainty:string;prior_outreach_count:number;evidence:{excerpt:string;url:string;checked_at:string;source_title:string};grounding:{facts?:string[];note_explanation?:string};events:OutreachEvent[];conversation:{closed_reason:string|null;next_action:string;followup_due:boolean}}
export interface OutreachEvent {id:number;kind:string;created_at:string;note:string;undone_at:string|null}
export interface Quality {recommended_contacts:number;needs_evidence:number;needs_review:number;notes_over_limit:number;contacted:number;replied:number;accepted:number;followups_due:number;reply_rate:number|null;acceptance_rate:number|null}
export interface Snapshot {applications:Application[];contacts:Contact[];baseline_valid:boolean;onboarding_required:boolean;demo:boolean;last_successful_sync:string;sync?:{state:string;error:string};quality:Quality}
export interface Filters {query:string;submission:string;sort:string}
export interface QueueGroup {application_id:string;role:string;submitted_at:string;contacts:Contact[]}
export interface CompanyGroup {key:string;company:string;contact_count:number;applications:QueueGroup[]}
export type {Configuration};
