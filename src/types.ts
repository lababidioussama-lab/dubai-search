export interface PropertyPrice {
  value?: number;
  currency?: string;
}

export interface PropertySummary {
  id?: number;
  externalID?: string;
  title?: string;
  price?: number;
  currency?: string;
  rentFrequency?: string;
  category?: Array<{ name?: string }>;
  location?: Array<{ name?: string; level?: number }>;
  rooms?: number;
  baths?: number;
  area?: number;
  purpose?: string;
  furnishingStatus?: string;
  completionStatus?: string;
  coverPhoto?: { url?: string };
  agency?: { name?: string; externalID?: string };
  createdAt?: number;
}

export interface PropertiesListResponse {
  hits?: PropertySummary[];
  nbHits?: number;
  page?: number;
  nbPages?: number;
  hitsPerPage?: number;
}

export interface PropertyDetail extends PropertySummary {
  description?: string;
  amenities?: Array<{ text?: string }>;
  phoneNumber?: { mobile?: string; phone?: string };
  photoCount?: number;
  contactName?: string;
  permitNumber?: string;
  geography?: { lat?: number; lng?: number };
}

export interface PropertyPhoto {
  id?: number;
  url?: string;
  title?: string;
}

export interface LocationSuggestion {
  id?: number;
  externalID?: string;
  name?: string;
  type?: string;
  hitsCount?: number;
}

export interface AgencySummary {
  id?: number;
  externalID?: string;
  name?: string;
  licenseNumber?: string;
  logo?: { url?: string };
  productLabel?: { tier?: string };
  verification?: { verified?: boolean };
}

export interface AgencyListResponse {
  hits?: AgencySummary[];
  nbHits?: number;
  page?: number;
  nbPages?: number;
}

export interface AgentSummary {
  id?: number;
  externalID?: string;
  name?: string;
  agency?: { name?: string; externalID?: string };
  phoneNumber?: { mobile?: string };
  email?: string;
  languages?: string[];
}

export interface AgentListResponse {
  hits?: AgentSummary[];
  nbHits?: number;
  page?: number;
  nbPages?: number;
}
