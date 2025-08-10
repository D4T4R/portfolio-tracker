import { extendTheme } from '@chakra-ui/react'
import { mode } from '@chakra-ui/theme-tools'

// Vibrant color palette
const colors = {
  brand: {
    50: '#E3F2FD',
    100: '#BBDEFB', 
    200: '#90CAF9',
    300: '#64B5F6',
    400: '#42A5F5',
    500: '#2196F3',
    600: '#1E88E5',
    700: '#1976D2',
    800: '#1565C0',
    900: '#0D47A1'
  },
  accent: {
    50: '#F3E5F5',
    100: '#E1BEE7',
    200: '#CE93D8',
    300: '#BA68C8',
    400: '#AB47BC',
    500: '#9C27B0',
    600: '#8E24AA',
    700: '#7B1FA2',
    800: '#6A1B9A',
    900: '#4A148C'
  },
  success: {
    50: '#E8F5E8',
    100: '#C8E6C9',
    200: '#A5D6A7',
    300: '#81C784',
    400: '#66BB6A',
    500: '#4CAF50',
    600: '#43A047',
    700: '#388E3C',
    800: '#2E7D32',
    900: '#1B5E20'
  },
  warning: {
    50: '#FFF8E1',
    100: '#FFECB3',
    200: '#FFE082',
    300: '#FFD54F',
    400: '#FFCA28',
    500: '#FFC107',
    600: '#FFB300',
    700: '#FFA000',
    800: '#FF8F00',
    900: '#FF6F00'
  },
  error: {
    50: '#FFEBEE',
    100: '#FFCDD2',
    200: '#EF9A9A',
    300: '#E57373',
    400: '#EF5350',
    500: '#F44336',
    600: '#E53935',
    700: '#D32F2F',
    800: '#C62828',
    900: '#B71C1C'
  }
}

const theme = extendTheme({
  config: {
    initialColorMode: 'dark',
    useSystemColorMode: false,
  },
  colors,
  fonts: {
    heading: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    body: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  },
  styles: {
    global: (props) => ({
      body: {
        bg: mode(
          'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
          'linear-gradient(135deg, #0f0f23 0%, #1a1a2e 50%, #16213e 100%)'
        )(props),
        minHeight: '100vh',
        backgroundAttachment: 'fixed',
      },
      '*': {
        scrollBehavior: 'smooth',
      },
    })
  },
  components: {
    Button: {
      baseStyle: {
        fontWeight: '600',
        borderRadius: '12px',
        transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
      },
      variants: {
        solid: (props) => ({
          bg: mode('brand.500', 'brand.600')(props),
          color: 'white',
          _hover: {
            bg: mode('brand.600', 'brand.700')(props),
            transform: 'translateY(-2px)',
            boxShadow: 'lg',
          },
          _active: {
            transform: 'translateY(0)',
          },
        }),
        gradient: {
          background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
          color: 'white',
          _hover: {
            background: 'linear-gradient(135deg, #5a67d8 0%, #667eea 100%)',
            transform: 'translateY(-2px)',
            boxShadow: 'xl',
          },
          _active: {
            transform: 'translateY(0)',
          },
        }
      }
    },
  },
  shadows: {
    'glow-sm': '0 0 10px rgba(102, 183, 255, 0.3)',
    'glow-md': '0 0 20px rgba(102, 183, 255, 0.4)',
    'glow-lg': '0 0 30px rgba(102, 183, 255, 0.5)',
  }
})

export default theme
