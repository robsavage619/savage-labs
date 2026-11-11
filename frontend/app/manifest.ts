import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Savage Labs",
    short_name: "Savage Labs",
    start_url: "/",
    display: "standalone",
    background_color: "#05070a",
    theme_color: "#05070a",
    icons: [{ src: "/apple-icon", sizes: "180x180", type: "image/png" }],
  };
}
