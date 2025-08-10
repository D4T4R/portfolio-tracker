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
import { motion } from 'framer-motion'

const MotionBox = motion(Box)
const springy = { type: 'spring', stiffness: 260, damping: 22, mass: 0.7 }

export default function StockCard({ name, data, portfolioData = null, totalPortfolioValue = null }) {
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
    // Open TradingView chart in new tab with default 1D timeframe
    const symbol = data.symbol.replace('.NS', '')
    const tradingViewUrl = `https://www.tradingview.com/chart/?symbol=NSE%3A${symbol}&interval=1D`
    window.open(tradingViewUrl, '_blank')
  }

  // Calculate portfolio percentage if data exists and totalPortfolioValue is available
  const portfolioPercentage = portfolioData && totalPortfolioValue ? 
    (((portfolioData.currentValue || portfolioData.netValue || 0) / totalPortfolioValue) * 100).toFixed(1) : null
  
  return (
    <MotionBox
      layoutId={`card-${data.symbol}`}
      bg={isHovered ? hoverBg : cardBg}
      border="1px solid"
      borderColor={isHovered ? hoverBorderColor : borderColor}
      borderRadius="xl"
      boxShadow={isHovered ? 'xl' : 'md'}
      p={6}
      cursor={portfolioData ? 'pointer' : 'default'}
      transition={springy}
      whileHover={{ y: -4, boxShadow: 'var(--chakra-shadows-xl)' }}
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
        borderRadius: '12px 12px 0 0'
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
          <>
            {/* Portfolio percentage badge */}
            {portfolioPercentage && (
              <Box textAlign="center" mt={1}>
                <Badge 
                  colorScheme="purple" 
                  variant="solid"
                  px={3}
                  py={1}
                  borderRadius="full"
                  fontSize="xs"
                >
                  {portfolioPercentage}% of portfolio
                </Badge>
              </Box>
            )}
            
            <Box 
              bg={useColorModeValue('gray.100', 'gray.700')} 
              p={4} 
              borderRadius="md"
              mt={2}
            >
              <VStack spacing={2} align="stretch">
                <Text fontSize="xs" color={useColorModeValue('gray.500', 'gray.400')} textAlign="center" fontWeight="semibold" textTransform="uppercase">
                  Your Holdings
                </Text>
                
                <HStack justify="space-between">
                  <Text fontSize="sm" color={useColorModeValue('gray.600', 'gray.300')} fontWeight="medium">
                    Shares
                  </Text>
                  <Text fontSize="sm" fontWeight="bold" color={useColorModeValue('gray.800', 'white')}>
                    {portfolioData.quantity || 0}
                  </Text>
                </HStack>
                
                <HStack justify="space-between">
                  <Text fontSize="sm" color={useColorModeValue('gray.600', 'gray.300')} fontWeight="medium">
                    Current Value
                  </Text>
                  <Text fontSize="sm" fontWeight="bold" color="blue.500">
                    ₹{(portfolioData.currentValue || portfolioData.netValue || 0).toLocaleString()}
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
                    {portfolioData.totalProfit >= 0 ? '+' : ''}₹{(portfolioData.totalProfit || 0).toLocaleString()}
                    {portfolioData.profitPercent !== undefined && (
                      <Text as="span" ml={1}>
                        ({portfolioData.profitPercent >= 0 ? '+' : ''}{portfolioData.profitPercent}%)
                      </Text>
                    )}
                  </Text>
                </HStack>
              </VStack>
            </Box>
          </>
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
    </MotionBox>
  )
}
