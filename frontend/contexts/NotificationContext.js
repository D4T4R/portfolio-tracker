import React, { createContext, useContext, useState, useEffect } from 'react'
import {
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  Box,
  VStack,
  CloseButton,
  useToast,
  Badge,
  HStack,
  Text
} from '@chakra-ui/react'
import { motion, AnimatePresence } from 'framer-motion'
import { FaArrowUp, FaArrowDown, FaBell } from 'react-icons/fa'

const NotificationContext = createContext()

export const useNotifications = () => {
  const context = useContext(NotificationContext)
  if (!context) {
    throw new Error('useNotifications must be used within a NotificationProvider')
  }
  return context
}

const MotionBox = motion(Box)
const MotionAlert = motion(Alert)

export const NotificationProvider = ({ children }) => {
  const [notifications, setNotifications] = useState([])
  const [previousPrices, setPreviousPrices] = useState({})
  const toast = useToast()

  // Check for significant price changes (>5%)
  const checkPriceAlerts = (currentPrices, portfolioData) => {
    if (!currentPrices || !portfolioData) return

    const alerts = []

    // Check each stock in portfolio for significant price changes
    portfolioData.portfolioData?.forEach(stock => {
      const stockName = stock.stockName
      const currentPrice = currentPrices.prices[stockName]
      const previousPrice = previousPrices[stockName]

      if (currentPrice && previousPrice && stock.quantity > 0) {
        const priceChange = ((currentPrice.price - previousPrice.price) / previousPrice.price) * 100

        if (Math.abs(priceChange) >= 5) {
          const isPositive = priceChange > 0
          const alertId = `${stockName}-${Date.now()}`

          alerts.push({
            id: alertId,
            type: isPositive ? 'success' : 'error',
            stockName,
            symbol: currentPrice.symbol,
            priceChange: priceChange.toFixed(2),
            currentPrice: currentPrice.price,
            previousPrice: previousPrice.price,
            impact: (priceChange / 100) * stock.currentValue,
            timestamp: new Date(),
            isPositive
          })

          // Show toast notification
          toast({
            title: `${isPositive ? '🚀' : '📉'} ${stockName}`,
            description: `${isPositive ? 'Surged' : 'Dropped'} by ${Math.abs(priceChange).toFixed(2)}% - Impact: ${isPositive ? '+' : ''}₹${((priceChange / 100) * stock.currentValue).toLocaleString()}`,
            status: isPositive ? 'success' : 'error',
            duration: 6000,
            isClosable: true,
            position: 'top-right',
            render: ({ onClose }) => (
              <MotionAlert
                initial={{ opacity: 0, x: 300, scale: 0.8 }}
                animate={{ opacity: 1, x: 0, scale: 1 }}
                exit={{ opacity: 0, x: 300, scale: 0.8 }}
                status={isPositive ? 'success' : 'error'}
                borderRadius="lg"
                boxShadow="xl"
                bg={isPositive ? 'green.500' : 'red.500'}
                color="white"
                border="none"
                position="relative"
                overflow="hidden"
                _before={{
                  content: '""',
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  right: 0,
                  height: '4px',
                  bg: isPositive ? 'green.300' : 'red.300'
                }}
              >
                <AlertIcon color="white" />
                <Box flex="1" mr={2}>
                  <HStack spacing={2} align="center" mb={1}>
                    <AlertTitle fontSize="md" color="white">
                      {isPositive ? '🚀' : '📉'} {stockName}
                    </AlertTitle>
                    <Badge 
                      colorScheme={isPositive ? 'green' : 'red'} 
                      variant="solid"
                      borderRadius="full"
                      px={2}
                    >
                      {isPositive ? '+' : ''}{priceChange.toFixed(2)}%
                    </Badge>
                  </HStack>
                  <AlertDescription color="whiteAlpha.900" fontSize="sm">
                    ₹{previousPrice.price} → ₹{currentPrice.price}
                    <Text as="span" fontWeight="bold" ml={2}>
                      Impact: {isPositive ? '+' : ''}₹{((priceChange / 100) * stock.currentValue).toLocaleString()}
                    </Text>
                  </AlertDescription>
                </Box>
                <CloseButton 
                  onClick={onClose}
                  color="whiteAlpha.900"
                  _hover={{ bg: 'whiteAlpha.200' }}
                />
              </MotionAlert>
            )
          })
        }
      }
    })

    if (alerts.length > 0) {
      setNotifications(prev => [...alerts, ...prev].slice(0, 10)) // Keep only latest 10
    }
  }

  const updatePrices = (currentPrices, portfolioData) => {
    if (Object.keys(previousPrices).length > 0) {
      checkPriceAlerts(currentPrices, portfolioData)
    }
    
    if (currentPrices?.prices) {
      setPreviousPrices(currentPrices.prices)
    }
  }

  const removeNotification = (id) => {
    setNotifications(prev => prev.filter(notif => notif.id !== id))
  }

  const clearAllNotifications = () => {
    setNotifications([])
  }

  const value = {
    notifications,
    updatePrices,
    removeNotification,
    clearAllNotifications
  }

  return (
    <NotificationContext.Provider value={value}>
      {children}
      
      {/* Floating Notifications Panel */}
      <AnimatePresence>
        {notifications.length > 0 && (
          <MotionBox
            initial={{ opacity: 0, y: -50 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -50 }}
            position="fixed"
            top="80px"
            right="20px"
            zIndex={9999}
            maxW="400px"
            w="full"
          >
            <Box
              bg="whiteAlpha.95"
              backdropFilter="blur(10px)"
              borderRadius="xl"
              border="1px solid"
              borderColor="whiteAlpha.300"
              boxShadow="xl"
              p={4}
              maxH="400px"
              overflowY="auto"
              css={{
                '&::-webkit-scrollbar': {
                  width: '4px',
                },
                '&::-webkit-scrollbar-track': {
                  background: 'transparent',
                },
                '&::-webkit-scrollbar-thumb': {
                  background: 'rgba(0,0,0,0.2)',
                  borderRadius: '4px',
                },
              }}
            >
              <HStack justify="space-between" align="center" mb={3}>
                <HStack>
                  <FaBell color="purple" />
                  <Text fontWeight="bold" color="gray.800">
                    Price Alerts
                  </Text>
                  <Badge colorScheme="purple" borderRadius="full">
                    {notifications.length}
                  </Badge>
                </HStack>
                <CloseButton
                  onClick={clearAllNotifications}
                  size="sm"
                  color="gray.600"
                  _hover={{ bg: 'red.100', color: 'red.600' }}
                />
              </HStack>

              <VStack spacing={2} align="stretch">
                <AnimatePresence>
                  {notifications.map((notification) => (
                    <MotionBox
                      key={notification.id}
                      initial={{ opacity: 0, x: 300 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: -300 }}
                      layout
                    >
                      <Alert
                        status={notification.isPositive ? 'success' : 'error'}
                        borderRadius="lg"
                        fontSize="sm"
                        p={3}
                        bg={notification.isPositive ? 'green.50' : 'red.50'}
                        border="1px solid"
                        borderColor={notification.isPositive ? 'green.200' : 'red.200'}
                        position="relative"
                      >
                        <AlertIcon />
                        <Box flex="1" mr={2}>
                          <HStack spacing={2} align="center" mb={1}>
                            <Text fontWeight="bold" fontSize="sm">
                              {notification.stockName}
                            </Text>
                            <Badge 
                              colorScheme={notification.isPositive ? 'green' : 'red'}
                              size="sm"
                            >
                              {notification.isPositive ? '+' : ''}{notification.priceChange}%
                            </Badge>
                          </HStack>
                          <Text fontSize="xs" color="gray.600">
                            Impact: {notification.isPositive ? '+' : ''}₹{notification.impact.toLocaleString()}
                          </Text>
                          <Text fontSize="xs" color="gray.500">
                            {notification.timestamp.toLocaleTimeString()}
                          </Text>
                        </Box>
                        <CloseButton
                          onClick={() => removeNotification(notification.id)}
                          size="sm"
                          color="gray.500"
                        />
                      </Alert>
                    </MotionBox>
                  ))}
                </AnimatePresence>
              </VStack>
            </Box>
          </MotionBox>
        )}
      </AnimatePresence>
    </NotificationContext.Provider>
  )
}
