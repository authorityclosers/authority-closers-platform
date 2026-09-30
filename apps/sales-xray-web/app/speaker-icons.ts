import {
  Anchor,
  Baby,
  BadgeCheck,
  Bike,
  BookOpen,
  Briefcase,
  Building2,
  Camera,
  Car,
  CircleUser,
  Code,
  Coffee,
  Crown,
  Dumbbell,
  Factory,
  Film,
  Gem,
  Globe,
  GraduationCap,
  Hammer,
  Handshake,
  Headset,
  HeartPulse,
  Hotel,
  House,
  Landmark,
  Laptop,
  Megaphone,
  Mic,
  Music,
  Package,
  Palette,
  PawPrint,
  Pill,
  Plane,
  Rocket,
  Scale,
  Scissors,
  Shirt,
  ShoppingBag,
  Sofa,
  Sprout,
  Stethoscope,
  Store,
  Sun,
  Tractor,
  Truck,
  User,
  UserRound,
  Users,
  UtensilsCrossed,
  Wrench,
  Zap,
  type LucideIcon,
} from "lucide-react";

export type SpeakerIcon = {
  key: string;
  label: string;
  /** People icons: offered to pick, never suggested from the report. */
  generic?: boolean;
  /** Words in a call's report that suggest this icon for the prospect. */
  keywords: string[];
  Icon: LucideIcon;
};

/**
 * The speaker icon library: people first, then the kinds of business a
 * prospect runs. Keys are stable; they are what gets saved.
 */
export const SPEAKER_ICONS: SpeakerIcon[] = [
  {
    generic: true,
    key: "person",
    label: "Person",
    keywords: [],
    Icon: UserRound,
  },
  { generic: true, key: "user", label: "User", keywords: [], Icon: User },
  {
    generic: true,
    key: "profile",
    label: "Profile",
    keywords: [],
    Icon: CircleUser,
  },
  {
    generic: true,
    key: "team",
    label: "Team",
    keywords: ["team", "partners"],
    Icon: Users,
  },
  {
    generic: true,
    key: "owner",
    label: "Owner",
    keywords: ["founder", "owner", "ceo", "director", "proprietor"],
    Icon: Crown,
  },
  {
    generic: true,
    key: "business",
    label: "Business",
    keywords: ["business", "company", "firm"],
    Icon: Briefcase,
  },
  {
    generic: true,
    key: "partner",
    label: "Partner",
    keywords: ["partner", "partnership"],
    Icon: Handshake,
  },
  {
    generic: true,
    key: "support",
    label: "Support",
    keywords: ["support", "call centre", "call center"],
    Icon: Headset,
  },
  {
    generic: true,
    key: "verified",
    label: "Verified",
    keywords: [],
    Icon: BadgeCheck,
  },
  {
    key: "carpentry",
    label: "Carpentry & building",
    keywords: [
      "carpentry",
      "carpenter",
      "furniture",
      "woodwork",
      "construction",
      "contractor",
      "civil",
    ],
    Icon: Hammer,
  },
  {
    key: "interiors",
    label: "Interiors",
    keywords: ["interior", "decor", "furnishing", "modular kitchen"],
    Icon: Sofa,
  },
  {
    key: "health",
    label: "Healthcare",
    keywords: ["doctor", "clinic", "hospital", "medical", "dentist", "dental"],
    Icon: Stethoscope,
  },
  {
    key: "wellness",
    label: "Wellness",
    keywords: ["wellness", "therapy", "physio", "nutrition", "diet"],
    Icon: HeartPulse,
  },
  {
    key: "pharmacy",
    label: "Pharmacy",
    keywords: ["pharmacy", "pharma", "chemist", "medicine"],
    Icon: Pill,
  },
  {
    key: "education",
    label: "Education",
    keywords: [
      "school",
      "coaching",
      "education",
      "teacher",
      "academy",
      "tuition",
      "institute",
      "college",
    ],
    Icon: GraduationCap,
  },
  {
    key: "courses",
    label: "Courses & books",
    keywords: ["course", "author", "publishing", "books"],
    Icon: BookOpen,
  },
  {
    key: "retail",
    label: "Retail",
    keywords: ["shop", "retail", "store", "showroom", "outlet"],
    Icon: Store,
  },
  {
    key: "ecommerce",
    label: "E-commerce",
    keywords: ["e-commerce", "ecommerce", "online store", "d2c"],
    Icon: ShoppingBag,
  },
  {
    key: "manufacturing",
    label: "Manufacturing",
    keywords: ["factory", "manufacturing", "manufacturer", "industrial"],
    Icon: Factory,
  },
  {
    key: "real-estate",
    label: "Real estate",
    keywords: ["real estate", "property", "builder", "realty", "developer"],
    Icon: Building2,
  },
  {
    key: "home-services",
    label: "Home services",
    keywords: ["home services", "cleaning", "pest control"],
    Icon: House,
  },
  {
    key: "food",
    label: "Food & restaurants",
    keywords: [
      "restaurant",
      "cafe",
      "food",
      "catering",
      "bakery",
      "cloud kitchen",
    ],
    Icon: UtensilsCrossed,
  },
  {
    key: "coffee",
    label: "Café",
    keywords: ["coffee", "tea"],
    Icon: Coffee,
  },
  {
    key: "hospitality",
    label: "Hospitality",
    keywords: ["hotel", "resort", "homestay", "hospitality"],
    Icon: Hotel,
  },
  {
    key: "salon",
    label: "Salon & beauty",
    keywords: ["salon", "beauty", "spa", "parlour", "parlor", "cosmetic"],
    Icon: Scissors,
  },
  {
    key: "fitness",
    label: "Fitness",
    keywords: ["gym", "fitness", "yoga", "trainer"],
    Icon: Dumbbell,
  },
  {
    key: "fashion",
    label: "Fashion & textiles",
    keywords: ["clothing", "garment", "textile", "fashion", "apparel"],
    Icon: Shirt,
  },
  {
    key: "jewellery",
    label: "Jewellery",
    keywords: ["jewellery", "jewelry", "jeweller", "diamond", "gold"],
    Icon: Gem,
  },
  {
    key: "automotive",
    label: "Automotive",
    keywords: ["automobile", "car", "dealership", "garage", "mechanic"],
    Icon: Car,
  },
  {
    key: "two-wheeler",
    label: "Two-wheelers",
    keywords: ["bike", "two-wheeler", "scooter", "cycle"],
    Icon: Bike,
  },
  {
    key: "travel",
    label: "Travel",
    keywords: ["travel", "tour", "tourism", "visa", "immigration"],
    Icon: Plane,
  },
  {
    key: "logistics",
    label: "Logistics",
    keywords: ["logistics", "transport", "courier", "shipping", "freight"],
    Icon: Truck,
  },
  {
    key: "export",
    label: "Import & export",
    keywords: ["export", "import", "trading"],
    Icon: Anchor,
  },
  {
    key: "wholesale",
    label: "Wholesale",
    keywords: ["wholesale", "distributor", "distribution", "supplier"],
    Icon: Package,
  },
  {
    key: "technology",
    label: "Technology",
    keywords: ["software", "saas", "it services", "technology", "tech"],
    Icon: Laptop,
  },
  {
    key: "developer",
    label: "Developer",
    keywords: ["app development", "web development", "programmer"],
    Icon: Code,
  },
  {
    key: "startup",
    label: "Startup",
    keywords: ["startup", "start-up"],
    Icon: Rocket,
  },
  {
    key: "finance",
    label: "Finance",
    keywords: [
      "bank",
      "finance",
      "accounting",
      "accountant",
      "chartered accountant",
      "insurance",
      "loan",
      "investment",
      "tax",
    ],
    Icon: Landmark,
  },
  {
    key: "legal",
    label: "Legal",
    keywords: ["lawyer", "legal", "advocate", "law firm"],
    Icon: Scale,
  },
  {
    key: "marketing",
    label: "Marketing",
    keywords: ["marketing", "advertising", "agency", "branding"],
    Icon: Megaphone,
  },
  {
    key: "design",
    label: "Design",
    keywords: ["design", "designer", "architect", "architecture"],
    Icon: Palette,
  },
  {
    key: "photo",
    label: "Photography",
    keywords: ["photography", "photographer", "wedding"],
    Icon: Camera,
  },
  {
    key: "media",
    label: "Media & film",
    keywords: ["film", "video", "production house", "media"],
    Icon: Film,
  },
  {
    key: "creator",
    label: "Creator & coach",
    keywords: ["podcast", "creator", "influencer", "speaker", "coach"],
    Icon: Mic,
  },
  {
    key: "music",
    label: "Music & events",
    keywords: ["music", "event", "events", "dj"],
    Icon: Music,
  },
  {
    key: "agriculture",
    label: "Agriculture",
    keywords: ["farm", "farming", "agriculture", "organic", "dairy"],
    Icon: Sprout,
  },
  {
    key: "equipment",
    label: "Equipment",
    keywords: ["tractor", "machinery", "equipment"],
    Icon: Tractor,
  },
  {
    key: "repairs",
    label: "Repairs & trades",
    keywords: ["repair", "plumbing", "plumber", "electrician", "maintenance"],
    Icon: Wrench,
  },
  {
    key: "energy",
    label: "Energy",
    keywords: ["electrical", "power", "energy", "battery"],
    Icon: Zap,
  },
  {
    key: "solar",
    label: "Solar",
    keywords: ["solar"],
    Icon: Sun,
  },
  {
    key: "kids",
    label: "Kids & childcare",
    keywords: ["preschool", "daycare", "kids", "toys"],
    Icon: Baby,
  },
  {
    key: "pets",
    label: "Pets",
    keywords: ["pet", "veterinary", "vet"],
    Icon: PawPrint,
  },
  {
    key: "global",
    label: "Global",
    keywords: ["international", "global", "overseas"],
    Icon: Globe,
  },
];

const BY_KEY = new Map(SPEAKER_ICONS.map((icon) => [icon.key, icon]));

export function speakerIcon(
  key: string | null | undefined,
): SpeakerIcon | null {
  return key ? (BY_KEY.get(key) ?? null) : null;
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * The icon whose keywords the report's own words mention most, for a
 * prospect nobody has given an icon yet. Falls back to a plain business icon.
 */
export function suggestProspectIcon(text: string): string {
  const lower = text.toLocaleLowerCase();
  let best = { key: "business", hits: 0 };
  for (const icon of SPEAKER_ICONS) {
    if (icon.generic) continue;
    let hits = 0;
    for (const keyword of icon.keywords) {
      const pattern = new RegExp(`\\b${escapeRegExp(keyword)}\\b`, "g");
      hits += lower.match(pattern)?.length ?? 0;
    }
    if (hits > best.hits) best = { key: icon.key, hits };
  }
  return best.key;
}

/** Search the library by label or keyword. */
export function searchSpeakerIcons(query: string): SpeakerIcon[] {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return SPEAKER_ICONS;
  return SPEAKER_ICONS.filter(
    (icon) =>
      icon.label.toLocaleLowerCase().includes(needle) ||
      icon.keywords.some((keyword) => keyword.includes(needle)),
  );
}
