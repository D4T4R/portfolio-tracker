import { ChakraProvider, extendTheme } from '@chakra-ui/react'

const theme = extendTheme({
  config: {
    initialColorMode: 'dark',
    useSystemColorMode: false,
  },
  colors: {
    brand: {
      50: '#e6f3ff',
      100: '#b3daff',
      200: '#80c1ff',
      300: '#4da8ff',
      400: '#1a8fff',
      500: '#0076e6',
      600: '#005cb3',
      700: '#004280',
      800: '#00284d',
      900: '#000e1a',
    },
    profit: {
      50: '#e6fffa',
      100: '#b3fff0',
      200: '#80ffe6',
      300: '#4dffdc',
      400: '#1affd2',
      500: '#00e6b8',
      600: '#00b390',
      700: '#008068',
      800: '#004d40',
      900: '#001a18',
    },
    loss: {
      50: '#ffe6e6',
      100: '#ffb3b3',
      200: '#ff8080',
      300: '#ff4d4d',
      400: '#ff1a1a',
      500: '#e60000',
      600: '#b30000',
      700: '#800000',
      800: '#4d0000',
      900: '#1a0000',
    }
  },
  styles: {
    global: {
      body: {
        bg: 'gray.900',
        color: 'white',
      },
    },
  },
})

function MyApp({ Component, pageProps }) {
  return (
    <ChakraProvider theme={theme}>
      <Component {...pageProps} />
    </ChakraProvider>
  )
}

export default MyApp
