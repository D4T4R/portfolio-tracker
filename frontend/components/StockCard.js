import {
  Box,
  Text,
  VStack,
  HStack,
  Badge,
  Stat,
  StatLabel,
  StatNumber,
  StatHelpText,
  IconButton,
  Flex,
  Tooltip,
  useColorModeValue,
  Button
} from '@chakra-ui/react'
import { FaChartLine } from 'react-icons/fa'
import { useRouter } from 'next/router'
import { useState } from 'react'

export default function StockCard({ name, data, portfolioData = null }) {
  const isPositive = data.change >= 0
  const changeColor = isPositive ? 'green.400' : 'red.400'
  const router = useRouter()
  const [isHovered, setIsHovered] = useState(false)
  
  const cardBg = useColorModeValue('white', 'gray.800')
  const hoverBg = useColorModeValue('gray.50', 'gray.700')
  const borderColor = useColorModeValue('gray.200', 'gray.600')
  const hoverBorderColor = useColorModeValue('blue.300', 'blue.500')

  const handleCardClick = () => {
    if (portfolioData) {
      // Navigate to portfolio detail with stock filter
      router.push({
        pathname: '/stock-detail',
        query: { 
          stockName: encodeURIComponent(name),
          symbol: data.symbol 
        }
      })
    }
  }

  const handleChartClick = (e) => {
    e.stopPropagation()
    // Check if user prefers internal charts or TradingView
    // For now, we'll provide both options via a context menu or use TradingView by default
    
    // Open internal chart page as default
    const chartUrl = `/chart/${data.symbol}`
    window.open(chartUrl, '_blank')
  }

  const handleTradingViewClick = (e) => {
    e.stopPropagation()
    // Open TradingView chart in new tab
    const symbol = data.symbol.replace('.NS', '')
    const tradingViewUrl = `https://www.tradingview.com/chart/?symbol=NSE%3A${symbol}&interval=1D`
    window.open(tradingViewUrl, '_blank')
  }
  
  return (
    <Box
      bg={isHovered ? hoverBg : cardBg}
      border="2px solid"
      borderColor={isHovered ? hoverBorderColor : borderColor}
      borderRadius="xl"
      boxShadow={isHovered ? '2xl' : 'lg'}
      p={6}
      cursor={portfolioData ? 'pointer' : 'default'}
      transition="all 0.3s ease"
      transform={isHovered ? 'translateY(-4px)' : 'translateY(0)'}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onClick={handleCardClick}
      position="relative"
      overflow="hidden"
      _before={{
        content: '""',
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        height: '4px',
        background: isPositive ? 'linear-gradient(90deg, #48BB78, #38A169)' : 'linear-gradient(90deg, #F56565, #E53E3E)',
        borderRadius: 'xl xl 0 0'
      }}
    >
      {/* Chart Button */}
      <Box position="absolute" top={4} right={4}>
        <Tooltip label="View Chart" placement="top">
          <IconButton
            icon={<FaChartLine />}
            size="sm"
            variant="ghost"
            colorScheme="blue"
            onClick={handleChartClick}
            _hover={{
              bg: 'blue.500',
              color: 'white',
              transform: 'scale(1.1)'
            }}
            transition="all 0.2s"
            aria-label="View stock chart"
          />
        </Tooltip>
      </Box>

      <VStack spacing={4} align="stretch" pt={2}>
        {/* Header */}
        <VStack spacing={2} align="start">
          <Text 
            fontSize="lg" 
            fontWeight="bold" 
            color={useColorModeValue('gray.800', 'white')}
            noOfLines={1}
            title={name}
          >
            {name}
          </Text>
          <Badge 
            colorScheme="blue" 
            variant="subtle"
            borderRadius="full"
            px={3}
            py={1}
            fontSize="xs"
            fontWeight="semibold"
          >
            {data.symbol}
          </Badge>
        </VStack>

        {/* Price Information */}
        <Stat>
          <StatLabel color={useColorModeValue('gray.600', 'gray.300')} fontSize="sm">
            Current Price
          </StatLabel>
          <StatNumber 
            color={useColorModeValue('gray.800', 'white')} 
            fontSize="2xl"
            fontWeight="bold"
          >
            ₹{data.price !== 'N/A' ? data.price.toLocaleString() : 'N/A'}
          </StatNumber>
          <StatHelpText color={changeColor} fontSize="sm" fontWeight="medium">
            <Flex align="center" gap={1}>
              <Text>{isPositive ? '+' : ''}₹{data.change}</Text>
              <Text>({isPositive ? '+' : ''}{data.changePercent}%)</Text>
            </Flex>
          </StatHelpText>
        </Stat>

        {/* Portfolio Information (if available) */}
        {portfolioData && (
          <Box 
            bg={useColorModeValue('gray.100', 'gray.700')} 
            p={4} 
            borderRadius="md"
            mt={2}
          >
            <VStack spacing={2} align="stretch">
              <HStack justify="space-between">
                <Text fontSize="sm" color={useColorModeValue('gray.600', 'gray.300')} fontWeight="medium">
                  Holdings
                </Text>
                <Text fontSize="sm" fontWeight="bold" color={useColorModeValue('gray.800', 'white')}>
                  {portfolioData.quantity} shares
                </Text>
              </HStack>
              
              <HStack justify="space-between">
                <Text fontSize="sm" color={useColorModeValue('gray.600', 'gray.300')} fontWeight="medium">
                  Current Value
                </Text>
                <Text fontSize="sm" fontWeight="bold" color={useColorModeValue('gray.800', 'white')}>
                  ₹{portfolioData.currentValue?.toLocaleString() || '0'}
                </Text>
              </HStack>
              
              <HStack justify="space-between">
                <Text fontSize="sm" color={useColorModeValue('gray.600', 'gray.300')} fontWeight="medium">
                  P&L
                </Text>
                <Text 
                  fontSize="sm" 
                  fontWeight="bold" 
                  color={portfolioData.totalProfit >= 0 ? 'green.500' : 'red.500'}
                >
                  {portfolioData.totalProfit >= 0 ? '+' : ''}₹{portfolioData.totalProfit?.toLocaleString() || '0'}
                  {portfolioData.profitPercent !== undefined && (
                    <Text as="span" ml={1}>
                      ({portfolioData.profitPercent >= 0 ? '+' : ''}{portfolioData.profitPercent}%)
                    </Text>
                  )}
                </Text>
              </HStack>
            </VStack>
          </Box>
        )}

        {/* Click to view hint for portfolio cards */}
        {portfolioData && (
          <Text 
            fontSize="xs" 
            color={useColorModeValue('gray.500', 'gray.400')} 
            textAlign="center"
            opacity={isHovered ? 1 : 0.7}
            transition="opacity 0.2s"
          >
            Click to view detailed portfolio info
          </Text>
        )}
      </VStack>
    </Box>
  )
}
