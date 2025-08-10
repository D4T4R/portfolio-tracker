import "../lib/axios-setup";
import { ChakraProvider, extendTheme } from "@chakra-ui/react";
import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import { useRouter } from "next/router";
import { useEffect } from "react";
import NProgress from "nprogress";
import "nprogress/nprogress.css";

const theme = extendTheme({
  config: { initialColorMode: "dark", useSystemColorMode: false },
  colors: {
    brand: { 50: "#e6f3ff", 100: "#b3daff", 200: "#80c1ff", 300: "#4da8ff", 400: "#1a8fff", 500: "#0076e6", 600: "#005cb3", 700: "#004280", 800: "#00284d", 900: "#000e1a" },
    profit:{ 50:"#e6fffa",100:"#b3fff0",200:"#80ffe6",300:"#4dffdc",400:"#1affd2",500:"#00e6b8",600:"#00b390",700:"#008068",800:"#004d40",900:"#001a18"},
    loss:{ 50:"#ffe6e6",100:"#ffb3b3",200:"#ff8080",300:"#ff4d4d",400:"#ff1a1a",500:"#e60000",600:"#b30000",700:"#800000",800:"#4d0000",900:"#1a0000"}
  },
  styles: { global: { body: { bg: "gray.900", color: "white" } } }
});

const MotionPage = motion("div");
const pageVariants = {
  initial: { opacity: 0, y: 12, filter: "blur(6px)" },
  animate: { opacity: 1, y: 0, filter: "blur(0px)" },
  exit: { opacity: 0, y: -12, filter: "blur(4px)" }
};
const pageTransition = { type: "spring", stiffness: 200, damping: 26, mass: 0.8 };

function MyApp({ Component, pageProps }) {
  const router = useRouter();

  useEffect(() => {
    NProgress.configure({ showSpinner: false, trickleSpeed: 120 });
    const start = () => NProgress.start();
    const done = () => NProgress.done();
    router.events.on("routeChangeStart", start);
    router.events.on("routeChangeComplete", done);
    router.events.on("routeChangeError", done);
    return () => {
      router.events.off("routeChangeStart", start);
      router.events.off("routeChangeComplete", done);
      router.events.off("routeChangeError", done);
    };
  }, [router.events]);

  return (
    <ChakraProvider theme={theme}>
      <MotionConfig reducedMotion="user">
        <AnimatePresence mode="wait" initial={false}>
          <MotionPage
            key={router.asPath}
            variants={pageVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            transition={pageTransition}
            style={{ minHeight: "100vh" }}
          >
            <Component {...pageProps} />
          </MotionPage>
        </AnimatePresence>
      </MotionConfig>
    </ChakraProvider>
  );
}

export default MyApp;